'use strict';
window.mountWriterGrowth=async function(){
 const root=document.querySelector('#growthWorkspace');if(!root||!S.pid)return;
 const data=await api('/writer-growth/projects/'+S.pid),g=data.genre;
 root.innerHTML='<div class="notice">القياس هنا يميز بين التقدم القابل للعد (الكلمات والمقاطع) وبين تقييمك الذاتي لمهارات الكتابة؛ لا توجد درجة جودة أدبية آلية مثبتة.</div>'+
 '<div class="grid two" style="margin-top:18px"><div class="card"><h3>رحلة '+esc(g.name)+'</h3><p>'+esc(g.promise)+'</p>'+
 '<div class="grid two"><div><b class="kpi">'+data.word_count.toLocaleString('ar')+'</b><p>كلمة في المخطوط تقريبًا</p></div><div><b class="kpi">'+data.section_count+'</b><p>مقطع أو مشهد</p></div></div>'+
 '<h4>المراحل المتخصصة</h4>'+g.stages.map((s,i)=>'<div class="list-item"><b>'+(i+1)+'. '+esc(s.label)+'</b><small>'+esc(s.description)+'</small></div>').join('')+
 '</div><div class="card"><h3>مراجعتك الذاتية</h3><p class="hint">اختر معيارًا ومرحلة، واكتب دليلًا من عملك وما تريد تحسينه. يمكن العودة لاحقًا لمقارنة ملاحظاتك.</p><form id="growthForm">'+
 '<label>المعيار<select name="dimension">'+g.dimensions.map(d=>'<option value="'+esc(d.key)+'">'+esc(d.label)+'</option>').join('')+'</select></label>'+
 '<label>المرحلة<select name="stage">'+g.stages.map(d=>'<option value="'+esc(d.key)+'">'+esc(d.label)+'</option>').join('')+'</select></label>'+
 '<label>ثقتك الحالية في إتقان هذا الجانب (تقييم ذاتي)<select name="confidence">'+[1,2,3,4,5].map(n=>'<option value="'+n+'">'+n+' / 5</option>').join('')+'</select></label>'+
 '<label>ما الدليل من كتابتك؟<textarea name="observation" minlength="5" maxlength="1500" required></textarea></label>'+
 '<label>ما الخطوة التالية؟<textarea name="next_action" minlength="5" maxlength="1000" required></textarea></label>'+
 '<button type="submit" class="primary">حفظ المراجعة</button></form></div></div>'+
 '<div class="card" style="margin-top:18px"><h3>تمارين تخصصية</h3><div class="grid">'+g.exercises.map((x,i)=>'<div class="card"><span class="pill">تمرين '+(i+1)+'</span><h4>'+esc(x.title)+'</h4><p>'+esc(x.question)+'</p></div>').join('')+'</div></div>'+
 '<div class="card" style="margin-top:18px"><h3>سجل تطورك الذاتي</h3>'+(data.checkins.length?data.checkins.map(x=>'<div class="list-item" style="display:block"><b>'+esc(g.dimensions.find(d=>d.key===x.dimension)?.label||x.dimension)+' · '+x.confidence+'/5</b><p>'+esc(x.observation)+'</p><small>خطوتك التالية: '+esc(x.next_action)+'</small></div>').join(''):'<p class="muted">ابدأ بمراجعة أولى، ثم عد للمقارنة بعد تعديل النص.</p>')+'</div>'+
 '<div class="card" style="margin-top:18px"><h3>تصدير احترافي قابل للتحرير</h3><p>ملف Word مرتب بالعربية يحوي المخطوط والمشاهد، مناسب لتقديمه للمحرر ومراجعته؛ لا يغني عن إعداد نسخة مطبعية نهائية.</p><a class="soft-btn" href="/api/pro-export/projects/'+S.pid+'/docx">تصدير Word</a></div>';
 root.querySelector('#growthForm').addEventListener('submit',async e=>{e.preventDefault();const f=e.currentTarget;try{await api('/writer-growth/projects/'+S.pid+'/checkins',{method:'POST',body:JSON.stringify({dimension:f.elements.dimension.value,stage:f.elements.stage.value,confidence:Number(f.elements.confidence.value),observation:f.elements.observation.value,next_action:f.elements.next_action.value})});toast('حُفظ التقييم الذاتي');await window.mountWriterGrowth()}catch(err){toast(err.message)}});
};
