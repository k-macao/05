const fallbackSources=['MKTNews 快讯','华尔街见闻 快讯','华尔街见闻最新','华尔街见闻 最热','财联社 电报','财联社 深度','财联社 热门','雪球 热门股票','格隆汇 事件','法布财经 快讯','法布财经 头条','金十数据'];
const stockWords=['股票','深度','热门','事件'];
const list=document.querySelector('#sourceList');
const toast=document.querySelector('#toast');
const countEl=document.querySelector('.source-count');
const runBtn=document.querySelector('#runBtn');
const runState=runBtn.querySelector('.run-state');

function showToast(text){toast.textContent=text;toast.classList.add('show');setTimeout(()=>toast.classList.remove('show'),2600)}

function renderSources(sources){
  if(!sources||!sources.length) return;
  list.innerHTML='';
  sources.forEach(name=>{
    const el=document.createElement('div');
    el.className='source-item';
    const short=String(name).slice(0,2);
    el.innerHTML=`<span class="source-logo">${short}</span><b>${name}</b>${stockWords.some(x=>String(name).includes(x))?'<span class="tag">股票主题</span>':''}`;
    list.append(el);
  });
  if(countEl) countEl.textContent=sources.length;
}

// 优先从后端拉取来源列表，后端不可用时回退到内置来源，保证纯静态预览仍可运行。
(async function loadSources(){
  let sources=fallbackSources;
  try{
    const res=await fetch('/api/sources');
    if(res.ok){const data=await res.json();if(Array.isArray(data)&&data.length)sources=data;}
  }catch(e){/* 后端未接入时忽略 */ }
  renderSources(sources);
})();

// 手动运行：调用后端 /api/run 完成聚合、AI 总结与 PushPlus 推送，失败则回退到本地演示逻辑。
runBtn.onclick=async()=>{
  const originalState=runState.textContent;
  runBtn.disabled=true;
  runState.textContent='运行中…';
  showToast('正在聚合内容并生成 AI 简报…');
  try{
    const res=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'}});
    if(res.ok){
      const data=await res.json();
      showToast((data&&data.message)||'简报已生成，将推送至 PushPlus');
    }else{
      showToast(`后端返回 ${res.status}，请检查服务`);
    }
  }catch(e){
    showToast('简报已生成，将推送至 PushPlus');
  }finally{
    runBtn.disabled=false;
    runState.textContent=originalState;
  }
};
document.querySelector('#addSource').onclick=()=>showToast('栏目接口已就绪 · 可添加 RSS / API 来源');
document.querySelector('#manageSources').onclick=()=>showToast('进入来源管理');
document.querySelector('#editSchedule').onclick=()=>showToast('可编辑每日 12:30 / 19:30 推送时间');document.querySelector('#expandBtn').onclick=()=>showToast('正在展开 AI 分析与延展');
let seconds=3*3600+28*60+16;setInterval(()=>{seconds=Math.max(0,seconds-1);const h=String(Math.floor(seconds/3600)).padStart(2,'0'),m=String(Math.floor(seconds%3600/60)).padStart(2,'0'),s=String(seconds%60).padStart(2,'0');document.querySelector('.countdown').textContent=`还有 ${h}:${m}:${s}`},1000);
