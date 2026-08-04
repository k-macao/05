const sources=['MKTNews 快讯','华尔街见闻 快讯','华尔街见闻最新','华尔街见闻 最热','财联社 电报','财联社 深度','财联社 热门','雪球 热门股票','格隆汇 事件','法布财经 快讯','法布财经 头条','金十数据'];
const stockWords=['股票','深度','热门','事件'];
const list=document.querySelector('#sourceList');
sources.forEach((name,i)=>{const el=document.createElement('div');el.className='source-item';const short=name.slice(0,2);el.innerHTML=`<span class="source-logo">${short}</span><b>${name}</b>${stockWords.some(x=>name.includes(x))?'<span class="tag">股票主题</span>':''}`;list.append(el)});
const toast=document.querySelector('#toast');
function showToast(text){toast.textContent=text;toast.classList.add('show');setTimeout(()=>toast.classList.remove('show'),2600)}
document.querySelector('#runBtn').onclick=()=>{showToast('正在聚合内容并生成 AI 简报…');setTimeout(()=>showToast('简报已生成，将推送至 PushPlus'),1700)};
document.querySelector('#addSource').onclick=()=>showToast('栏目接口已就绪 · 可添加 RSS / API 来源');
document.querySelector('#manageSources').onclick=()=>showToast('进入来源管理');
document.querySelector('#editSchedule').onclick=()=>showToast('可编辑每日 12:30 / 19:30 推送时间');document.querySelector('#expandBtn').onclick=()=>showToast('正在展开 AI 分析与延展');
let seconds=3*3600+28*60+16;setInterval(()=>{seconds=Math.max(0,seconds-1);const h=String(Math.floor(seconds/3600)).padStart(2,'0'),m=String(Math.floor(seconds%3600/60)).padStart(2,'0'),s=String(seconds%60).padStart(2,'0');document.querySelector('.countdown').textContent=`还有 ${h}:${m}:${s}`},1000);