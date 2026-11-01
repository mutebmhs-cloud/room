'use strict';
// Provider tools are available only to signed-in accounts; the directory is self-declared.
window.renderPartnerWidgets=async function(){
 const host=document.querySelector('#serviceWorkspace');if(!host)return;
 let directory=[],invitations=[];
 try{[directory,invitations]=await Promise.all([api('/partners/directory'),api('/partners/invitations')])}catch(e){toast(e.message);return}
 const panel=document.createElement('div');panel.className='card';panel.style.marginTop='18px';panel.innerHTML=
 '<h3>شبكة مقدمي الخدمات — تجريبية</h3><p class="notice">الملفات المهنية غير متحقق منها. لا يوجد تعاقد أو دفع أو التزام بالتنفيذ من المنصة.</p>'+
 '<details><summary>إضافة ملفك كمقدم خدمة</summary><form id="partnerProfileForm"><label>اسم العرض<input name="display_name" required minlength="2" maxlength="100"></label><label>نبذة مهنية<textarea name="bio" required minlength="12" maxlength="1200"></textarea></label><label>التخصص<select name="specialty">'+(await api('/services/catalog')).map(x=>'<option value="'+esc(x.key)+'">'+esc(x.name)+'</option>').join('')+'</select></label><button class="primary" type="submit">تسجيل الملف المهني غير المتحقق منه</button></form></details>'+
 '<h4>مقدمو الخدمات المتاحون للتواصل التجريبي</h4><div id="partnerList">'+(directory.length?directory.map(p=>'<div class="list-item"><div><b>'+esc(p.display_name)+'</b><small style="display:block">'+esc(p.bio.slice(0,150))+' · غير متحقق منه</small></div><button class="small-btn" data-invite-provider="'+p.user_id+'">دعوة</button></div>').join(''):'<p class="muted">لا توجد ملفات مهنية مسجلة بعد.</p>')+'</div>'+
 '<h4>الدعوات الواردة إليك</h4><div id="partnerInbox">'+(invitations.length?invitations.map(i=>'<div class="list-item"><div><b>'+esc(i.title)+'</b><small style="display:block">'+esc(i.status)+' · '+esc(i.brief||'التفاصيل متاحة بعد القبول')+'</small></div>'+(i.status==='pending'?'<button class="small-btn" data-decision="'+i.id+'" data-value="accepted">قبول</button><button class="small-btn" data-decision="'+i.id+'" data-value="declined">رفض</button>':i.status==='accepted'?'<button class="small-btn" data-open-job="'+i.request_id+'">عرض الطلب</button>':'')+'</div>').join(''):'<p class="muted">لا توجد دعوات واردة.</p>')+'</div><div id="partnerJob"></div>';
 host.appendChild(panel);
 panel.querySelector('#partnerProfileForm').addEventListener('submit',async e=>{e.preventDefault();const form=e.currentTarget;
  try{await api('/partners/profile',{method:'POST',body:JSON.stringify({display_name:form.elements.display_name.value,bio:form.elements.bio.value,specialties:[form.elements.specialty.value]})});toast('حُفظ الملف المهني دون شارة تحقق');await window.mountCulturalServices()}catch(err){toast(err.message)}
 });
 panel.addEventListener('click',async e=>{
  const btn=e.target.closest('button[data-invite-provider],button[data-decision],button[data-open-job]');if(!btn)return;
  try{
   if(btn.dataset.inviteProvider){
    const provider=directory.find(p=>p.user_id===Number(btn.dataset.inviteProvider));
    const jobs=await api('/services/requests?project_id='+S.pid);
    const options=jobs.filter(x=>(x.route==='human'||x.route==='hybrid')&&x.status!=='cancelled'&&x.status!=='accepted'&&provider.specialties.includes(x.service_key));
    if(!options.length){toast('أنشئ أولًا طلبًا بشريًا أو مختلطًا في تخصص مقدم الخدمة');return}
    const id=options[0].id;
    if(!confirm('إرسال دعوة للمختص '+provider.display_name+' بخصوص الطلب '+options[0].title+'؟ سيطلع على الموجز أولًا، وعلى المقاطع المختارة بعد القبول.'))return;
    await api('/partners/requests/'+id+'/invite',{method:'POST',body:JSON.stringify({provider_id:provider.user_id})});toast('أُرسلت دعوة تجريبية');
   }else if(btn.dataset.decision){
    await api('/partners/invitations/'+btn.dataset.decision+'/decision',{method:'POST',body:JSON.stringify({decision:btn.dataset.value})});await window.mountCulturalServices();
   }else if(btn.dataset.openJob){
    const job=await api('/partners/work/'+btn.dataset.openJob);
    panel.querySelector('#partnerJob').innerHTML='<h4>المهمة المقبولة: '+esc(job.title)+'</h4><p>'+esc(job.brief)+'</p><p class="hint">المقاطع المتاحة بإذن صاحب الطلب: '+job.shared_section_count+'</p>'+
      job.shared_sections.map(s=>'<details><summary>'+esc(s.title)+'</summary><p style="white-space:pre-wrap">'+esc(s.body||s.blocks.map(b=>b.text).join(' '))+'</p></details>').join('')+
      '<form id="providerReply"><label>ملاحظة إلى صاحب العمل<textarea name="body" minlength="2" required></textarea></label><button class="primary">إرسال الملاحظة داخل المنصة</button></form>';
    panel.querySelector('#providerReply').addEventListener('submit',async ev=>{ev.preventDefault();try{await api('/partners/work/'+job.id+'/messages',{method:'POST',body:JSON.stringify({body:ev.currentTarget.elements.body.value})});toast('حُفظت الملاحظة');ev.currentTarget.reset()}catch(err){toast(err.message)}});
   }
  }catch(err){toast(err.message)}
 });
};
