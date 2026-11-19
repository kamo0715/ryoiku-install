(() => {
  'use strict';
  const list=document.getElementById('day-plan-list');
  if(!list)return;
  const form=document.getElementById('day-flow-form');
  const blocks=()=>Array.from(list.querySelectorAll('[data-day-plan]'));
  const checked=b=>b.querySelector('[data-day-include]').checked;
  const order=b=>b.querySelector('[data-day-order]');
  const selected=()=>blocks().filter(checked).sort((a,b)=>Number(order(a).value||99)-Number(order(b).value||99));
  const updatePreview=()=>{
    const active=selected();
    const preview=document.getElementById('day-flow-preview');
    if(!preview)return;
    let total=0;
    const names=[];
    active.forEach((block,index)=>{
      const inputs=Array.from(block.querySelectorAll('[data-plan-editor] .day-step [data-minutes]'));
      const duration=inputs.reduce((v,input)=>v+(Number(input.value)||0),0);
      total+=duration;
      const title=block.querySelector('.day-plan-head strong')?.textContent?.trim()||`活動${index+1}`;
      names.push(`${index+1}. ${title}（${duration}分）`);
      if(index<active.length-1){
        const gap=block.querySelector('.day-between [data-minutes]');
        if(gap&&gap.value)total+=Number(gap.value)||0;
      }
    });
    for(const pos of ['before','after']){
      form.querySelectorAll(`input[name^="${pos}_"][data-minutes]`).forEach(el=>total+=Number(el.value)||0);
    }
    const start=form.querySelector('[name="start_time"]')?.value;
    let time='';
    if(start&&/^\d\d:\d\d$/.test(start)){
      const [h,m]=start.split(':').map(Number),end=h*60+m+total;
      time=end<1440?`／終了目安 ${String(Math.floor(end/60)).padStart(2,'0')}:${String(end%60).padStart(2,'0')}`:'／翌日までの予定は出力不可';
    }
    preview.textContent=`選択 ${active.length}件／合計約${total}分${time}\n${names.join(' → ')}`;
  };
  const updateVisibility=()=>{
    const active=selected();
    blocks().forEach(b=>{
      const enabled=checked(b);
      const editor=b.querySelector('[data-plan-editor]');
      editor.hidden=!enabled;
      editor.querySelectorAll('input,textarea,select').forEach(input=>{input.disabled=!enabled;});
      const field=order(b);
      if(enabled&&!field.value)field.value=String(active.length);
      field.disabled=!enabled;
    });
    const tooMany=active.length>8;
    if(tooMany){
      const last=active[active.length-1];
      last.querySelector('[data-day-include]').checked=false;
      const editor=last.querySelector('[data-plan-editor]');
      editor.hidden=true;editor.querySelectorAll('input,textarea,select').forEach(input=>{input.disabled=true;});
      order(last).disabled=true;
      window.alert('1日に選択できるのは最大8件です。');
    }
    updatePreview();
  };
  const normalize=()=>{selected().forEach((b,index)=>order(b).value=String(index+1));updateVisibility();};
  list.addEventListener('change',e=>{
    if(e.target.matches('[data-day-include]')){
      if(checked(e.target.closest('[data-day-plan]')))order(e.target.closest('[data-day-plan]')).value=String(selected().length);
      normalize();
    }else if(e.target.matches('[data-day-order]'))updatePreview();
  });
  list.addEventListener('click',e=>{
    const btn=e.target.closest('[data-move-up],[data-move-down]');
    if(!btn)return;
    const block=btn.closest('[data-day-plan]');
    if(!checked(block))return;
    const arr=selected(),i=arr.indexOf(block);
    const swap=btn.matches('[data-move-up]')?i-1:i+1;
    if(swap<0||swap>=arr.length)return;
    const other=arr[swap];
    const previous=order(block).value;
    order(block).value=order(other).value;order(other).value=previous;
    updatePreview();
  });
  form.addEventListener('input',e=>{if(e.target.matches('[data-minutes],[name="start_time"]'))updatePreview();});
  // Initial active plan stays included; server independently validates it.
  updateVisibility();
})();
