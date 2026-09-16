// github.io（GitHub Pages）是纯静态托管：POST /api/run 必然 405，
// 定时/手动推送由 GitHub Actions 完成，按钮在此环境下改为跳转 Actions。
const isGithubPages=location.hostname.endsWith('.github.io');
const ACTIONS_URL='https://github.com/k-macao/05/actions/workflows/daily-push.yml';
const toast=document.querySelector('#toast');
const runBtn=document.querySelector('#runBtn');
const runState=runBtn.querySelector('.run-state');
const refreshBtn=document.querySelector('#refreshBtn');

function showToast(text,ms=2600){
  toast.textContent=text;
  toast.classList.add('show');
  setTimeout(()=>toast.classList.remove('show'),ms);
}

// 手动运行：调用后端 /api/run 完成聚合、AI 总结与 PushPlus 推送；github.io 静态托管下改为跳转 Actions 手动触发。
runBtn.onclick=async()=>{
  if(isGithubPages){
    showToast('GitHub Pages 为纯静态托管，已打开 Actions 手动触发每日推送');
    window.open(ACTIONS_URL,'_blank');
    return;
  }
  const originalState=runState.textContent;
  runBtn.disabled=true;
  runState.textContent='运行中…';
  showToast('正在聚合内容并生成 AI 简报…');
  try{
    const res=await fetch('api/run',{method:'POST',headers:{'Content-Type':'application/json'}});
    if(res.ok){
      const data=await res.json();
      showToast((data&&data.message)||'简报已生成，将推送至 PushPlus');
    }else{
      // 优先展示服务端返回的真实原因（如 503 未配置 token、409 大盘数据非最新已拦截），
      // 静态托管等场景下 405 给出明确指引。
      let message=null;
      try{const data=await res.json();if(data&&data.message)message=data.message;}catch(e){/* 非 JSON 错误体 */ }
      if(res.status===405) message='当前页面由静态托管提供，不支持 POST /api/run，请改用 server.py 启动服务';
      showToast(message||`后端返回 ${res.status}，请检查服务`,res.status===409?6000:2600);
    }
  }catch(e){
    showToast('无法连接推送服务，请确认后端正在运行');
  }finally{
    runBtn.disabled=false;
    runState.textContent=originalState;
  }
};

document.querySelector('#editSchedule').onclick=()=>showToast('可编辑每日 12:30 / 19:30 推送时间');
document.querySelector('#expandBtn').onclick=()=>showToast('正在展开 AI 分析与延展');
if(refreshBtn)refreshBtn.onclick=()=>showToast('内容已刷新');

// Schedule toggle persistence
document.querySelectorAll('.pixel-switch input[data-toggle]').forEach(input=>{
  const key='schedule_'+input.dataset.toggle;
  const saved=localStorage.getItem(key);
  if(saved!==null)input.checked=saved==='1';
  input.onchange=()=>{
    localStorage.setItem(key,input.checked?'1':'0');
    showToast(input.checked?'已开启推送':'已关闭推送');
  };
});
