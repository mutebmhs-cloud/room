'use strict';
// Companion to app.js. The service module never sends manuscript text to external providers.
window.mountCulturalServices=async function(){
 const root=document.querySelector('#serviceWorkspace');if(!root||!S.project)return;
 const [catalog,requests]=await Promise.all([api('/services/catalog'),api('/services/requests?project_id='+S.pid)]);
 const allowed=catalog.filter(x=>x.kinds.includes(S.project.kind));
 const routes={human:'متخصص بشري',ai:'ذكاء اصطناعي متخصص',hybrid:'ذكاء اصطناعي + مراجعة بشرية'};
 root.innerHTML='<div class="notice">نسخة طلبات تجريبية: لا توجد جهات بشرية متصلة ولا معالجة ذكاء اصطناعي حية. لا تشارك مخطوطات حقيقية. كل طلب يبقى في حساب صاحبه.</div>'+
 '<div class="grid two" style="margin-top:18px"><div class="card"><h3>طلب خدمة للمشروع</h3><p>اختر التخصص وطريقة التنفيذ، وشارك مقاطع محددة فقط بموافقتك.</p><form id="serviceRequestForm">'+
 '<label>الخدمة<select name="service_key" id="srvKind">'+allowed.map(s=>'<option value="'+esc(s.key)+'">'+esc(s.name)+'</option>').join('')+'</select></label>'+
 '<p id="srvProblem" class="hint"></p><label>طريقة التنفيذ<select id="srvRoute" name="route"></select></label>'+
 '<label>عنوان الطلب<input name="title" required minlength="3" maxlength="180" placeholder="مثال: تدقيق الفصل الأول"></label>'+
 '<label>وصف المطلوب والنتيجة المتوقعة<textarea name="brief" required minlength="12" maxlength="4000" placeholder="حدد نوع التدقيق والمعايير المطلوبة"></textarea></label>'+
 '<div class="card" style="padding:12px;background:#f8fbf9"><b>المقاطع التي تسمح بإرفاق نسخة منها</b><p class="hint">المقاطع غير المحددة ستبقى خاصة. يُحفظ نص المقاطع المحددة كنسخة ثابتة لهذا الطلب، ولا يُرسل إلى أي جهة خارجية.</p>'+
 (S.sections.length?S.sections.map(s=>'<label class="checkrow"><input type="checkbox" class="srvShare" value="'+s.id+'"> '+esc(s.title)+' (نسخة '+s.version+')</label>').join(''):'<p class="hint">لم تضف مقاطع بعد؛ يمكنك تقديم موجز الطلب فقط.</p>')+
 '</div><label class="checkrow" id="srvConsentLabel" hidden><input type="checkbox" id="srvConsent"> أطلب خدمة ذكاء اصطناعي وأوافق مبدئيًا على استخدام المقاطع المختارة، مع علمي أن الاتصال الفعلي بالمزود غير متاح في هذه النسخة. يلزم إذن جديد عند التنفيذ الفعلي.</label>'+
 '<label class="checkrow"><input type="checkbox" id="srvConfirm" required> أؤكد أن الوصف والمقاطع المختارة فقط هي ما أريد تضمينه في الطلب.</label>'+
 '<button class="primary" type="submit">حفظ طلب الخدمة</button></form></div>'+
 '<div class="card"><h3>الطلبات الخاصة بهذا المشروع</h3><div id="serviceRequests">'+(requests.length?requests.map(x=>'<button class="list-item" style="width:100%;text-align:right;display:block;margin-bottom:8px" data-service-request="'+x.id+'"><b>'+esc(x.title)+'</b><small style="display:block">'+esc(x.status)+' · '+esc(routes[x.route])+' · '+x.shared_section_count+' مقطع</small></button>').join(''):'<p class="muted">لا توجد طلبات بعد.</p>')+'</div><div id="serviceDetail"></div></div></div>';
 const kind=root.querySelector('#srvKind'),route=root.querySelector('#srvRoute'),consent=root.querySelector('#srvConsentLabel');
 function sync(){const s=allowed.find(x=>x.key===kind.value);root.querySelector('#srvProblem').textContent=s?.problem||'';route.innerHTML=(s?.routes||[]).map(x=>'<option value="'+x+'">'+routes[x]+'</option>').join('');toggle()}
 function toggle(){consent.hidden=route.value==='human';root.querySelector('#srvConsent').checked=false}
 kind.addEventListener('change',sync);route.addEventListener('change',toggle);sync();
 root.querySelector('#serviceRequestForm').addEventListener('submit',async event=>{
  event.preventDefault();const form=event.currentTarget;
  const payload={project_id:S.pid,service_key:kind.value,route:route.value,title:form.elements.title.value,
   brief:form.elements.brief.value,section_ids:[...root.querySelectorAll('.srvShare:checked')].map(x=>Number(x.value)),
   allow_ai_processing:!consent.hidden&&root.querySelector('#srvConsent').checked};
  try{await api('/services/requests',{method:'POST',body:JSON.stringify(payload)});toast('حُفظ الطلب في مساحة المشروع دون إرسال خارجي');await window.mountCulturalServices()}
  catch(e){toast(e.message)}
 });
 if(window.renderPartnerWidgets)await window.renderPartnerWidgets();
 root.addEventListener('click',async e=>{
  const btn=e.target.closest('[data-service-request]');if(!btn)return;
  const req=await api('/services/requests/'+btn.dataset.serviceRequest);
  const detail=root.querySelector('#serviceDetail');
  detail.innerHTML='<hr class="subtle-sep"><h3>'+esc(req.title)+'</h3><p>'+esc(req.brief)+'</p><p class="hint">الحالة: '+esc(req.status)+' · المقاطع المرفقة: '+req.shared_section_count+' · التنفيذ: غير متصل</p>'+
   (req.shared_sections.length?'<details><summary>معاينة المقاطع التي سمحت بمشاركتها</summary>'+req.shared_sections.map(s=>'<div class="card"><b>'+esc(s.title)+'</b><p>'+esc(s.body||s.blocks.map(b=>b.text).join(' ')).slice(0,3000)+'</p></div>').join('')+'</details>':'')+
   '<h4>ملاحظات الطلب</h4>'+(req.messages.map(m=>'<p class="aside-note">'+esc(m.body)+'</p>').join('')||'<p class="muted">لا توجد ملاحظات</p>')+
   (req.status==='cancelled'||req.status==='accepted'?'':'<form id="srvNoteForm"><label>أضف ملاحظة للطلب<textarea name="body" required minlength="2" maxlength="3000"></textarea></label><button class="soft-btn">حفظ الملاحظة</button></form><button class="soft-btn danger" id="srvCancel">إلغاء الطلب</button>');
  const note=detail.querySelector('#srvNoteForm');if(note)note.addEventListener('submit',async ev=>{ev.preventDefault();try{await api('/services/requests/'+req.id+'/messages',{method:'POST',body:JSON.stringify({body:note.elements.body.value})});toast('حُفظت الملاحظة');btn.click()}catch(err){toast(err.message)}});
  const cancel=detail.querySelector('#srvCancel');if(cancel)cancel.addEventListener('click',async()=>{if(!confirm('إلغاء طلب الخدمة؟'))return;try{await api('/services/requests/'+req.id+'/state',{method:'POST',body:JSON.stringify({status:'cancelled'})});await window.mountCulturalServices()}catch(err){toast(err.message)}});
 });
};
