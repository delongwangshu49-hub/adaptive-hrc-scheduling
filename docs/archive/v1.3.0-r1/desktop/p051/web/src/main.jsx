import React,{useEffect,useMemo,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import Timeline from './Timeline.jsx';
import {Welcome,Summary,Setup,Inspector,Support,ErrorBanner} from './Experience.jsx';
import {appVersion,archiveProgress} from './experience.mjs';
import {navigationSettings,rangeOf,timeLabel} from './gantt-model.mjs';
import {makePayload} from './model.mjs';
import './style.css';
import './experience.css';

import {SceneTools,ContextStrip,Events,SceneEmpty} from './LinkedExperience.jsx';
import {rowForEntity,selectedEntity,restoreSelection,viewCamera} from './linkage.mjs';
let nativeBridge;
const calls=[];
function rpc(action,data={}){
  return new Promise((resolve,reject)=>{
    const run=()=>nativeBridge.invoke(JSON.stringify({action,data}),raw=>{try{const r=JSON.parse(raw);r.ok?resolve(r.data):reject(Error(r.error));}catch(e){reject(e);}});
    nativeBridge?run():calls.push(run);
  });
}
const words={
zh:{title:'连续生产工作台',start:'启动配置',open:'打开会话',normal:'普通单',urgent:'急单',people:'人员变更',more:'更多事件',close:'关闭接单',stop:'安全停止',restore:'恢复等分',language:'English',native:'Isaac 三维',gantt:'实时甘特',maximize:'双图放大',camera:'相机',locate:'定位所选',operation:'工序',resource:'资源',all:'全部产品',filter:'筛选工作',compare:'旧新对比',export:'导出',detail:'详情与回执',unknown:'未知',disconnected:'未连接',waiting:'等待已验证投影',unplanned:'未排 · 无计划区间',actual:'实际',committed:'承诺',tentative:'预测',unscheduled:'未排',candidate:'候选',adopted:'采用',superseded:'旧方案',preview:'核对参数',confirm:'确认提交',cancel:'关闭表单',target:'对象 ID',template:'模板',quantity:'数量',due:'交期 (h)',priority:'优先级',position:'到岗位置',initial:'初始 F',reason:'原因代码',repair:'维修证据',duration:'休息时长 (h)',normalOption:'普通',urgentOption:'紧急',request:'请求',effective:'生效',business:'业务结果',fresh:'已验证',stale:'陈旧',source:'来源',age:'帧龄',setup:'运行配置',variant:'初始产品模板',products:'初始件数',method:'调度方法',backend:'执行后端',rate:'模拟倍率 (h/s)',startNow:'确认启动',noSelection:'选择工作查看来源、详情和原始标识',evidence:'打开证据目录',query:'查询原请求',empty:'当前筛选没有已交付工作',focus:'所选工作',identity:'工作身份',collision:'四色邻接冲突',readonly:'只读',time:'模拟时间',mode:'状态',accepted:'已接纳',form:'运行中输入',saved:'保存会话 · 只读',scroll:'滚轮平移 · Ctrl+滚轮缩放',safe:'停止后完成安全段，业务结果以原回执为准',actualParams:'实际提交参数',pending:'处理中',personTemplate:'资格/日历模板',timeRule:'生效规则',at:'指定模拟时刻 (h)',expires:'最晚生效 (h)',immediate:'立即合法边界',atTime:'指定时刻',material:'物料计划',jit:'模板及时到达',delay:'模板延迟1h',none:'尚无请求',details:'展开详情',collapse:'折叠',selection:'共享选择',nativeState:'原生视口',connecting:'连接中',viewOnly:'视图操作不发送业务请求',requestSubmitted:'已发送 · 等待回执',unknownReceipt:'未获得确认 · 查询原 ID',begin:'起点 (h)',span:'跨度 (h)',zoom:'缩放',cancelOrder:'取消订单',depart:'计划离岗',absent:'突发缺勤',return:'同 ID 返回',arrive:'新增到岗',rest:'休息请求',failure:'设备故障',repaired:'设备维修',fence:'关闭接单',warning:'状态待核对',future:'未交付内容不显示'},
en:{title:'Production Workbench',start:'Run setup',open:'Open session',normal:'New order',urgent:'Urgent order',people:'People',more:'More events',close:'Close intake',stop:'Safe stop',restore:'Equal split',language:'简体中文',native:'Isaac 3D',gantt:'Live timeline',maximize:'Enlarge both',camera:'Camera',locate:'Locate selection',operation:'Operations',resource:'Resources',all:'All products',filter:'Filter work',compare:'Old / new',export:'Export',detail:'Details & receipts',unknown:'Unknown',disconnected:'Disconnected',waiting:'Waiting for verified projection',unplanned:'Unscheduled · no interval',actual:'Actual',committed:'Committed',tentative:'Tentative',unscheduled:'Unscheduled',candidate:'Candidate',adopted:'Adopted',superseded:'Previous plan',preview:'Review parameters',confirm:'Confirm submit',cancel:'Close form',target:'Object ID',template:'Template',quantity:'Quantity',due:'Due time (h)',priority:'Priority',position:'Arrival location',initial:'Initial F',reason:'Reason code',repair:'Repair evidence',duration:'Rest duration (h)',normalOption:'Normal',urgentOption:'Urgent',request:'Request',effective:'Effective',business:'Business result',fresh:'Verified',stale:'Stale',source:'Source',age:'Frame age',setup:'Run configuration',variant:'Initial template',products:'Initial quantity',method:'Scheduling method',backend:'Backend',rate:'Simulation rate (h/s)',startNow:'Confirm start',noSelection:'Select work to inspect its source and original identity',evidence:'Open evidence folder',query:'Query original ID',empty:'No delivered work matches these filters',focus:'Selected work',identity:'Work identity',collision:'Adjacent color collision',readonly:'Read only',time:'Simulation time',mode:'State',accepted:'Accepted',form:'Runtime input',saved:'Saved session · read only',scroll:'Wheel pans · Ctrl+wheel zooms',safe:'Safe segments drain after stop; original receipts define the result',actualParams:'Exact submission parameters',pending:'Working',personTemplate:'Qualification / calendar template',timeRule:'Effective rule',at:'Requested sim time (h)',expires:'Latest effective time (h)',immediate:'Next legal boundary',atTime:'At sim time',material:'Material plan',jit:'Template just in time',delay:'Template delayed 1h',none:'No requests yet',details:'Show details',collapse:'Collapse',selection:'Shared selection',nativeState:'Native viewport',connecting:'Connecting',viewOnly:'View actions never submit business changes',requestSubmitted:'Submitted · awaiting receipt',unknownReceipt:'Unconfirmed · query original ID',begin:'Start (h)',span:'Span (h)',zoom:'Zoom',cancelOrder:'Cancel order',depart:'Planned departure',absent:'Unexpected absence',return:'Same-ID return',arrive:'New arrival',rest:'Rest request',failure:'Device failure',repaired:'Device repair',fence:'Close intake',warning:'State needs review',future:'Undelivered content stays hidden'}
};
const savedContext=(()=>{try{return JSON.parse(sessionStorage.getItem('p051-view')||'{}')}catch{return {}}})();
words.zh.updateOrder='修改优先级/交期';words.en.updateOrder='Edit priority / due';
words.zh.planned='完整计划';words.en.planned='Full plan';words.zh.current_plan='当前完整计划';words.en.current_plan='Current full plan';
words.zh.events='事件点';words.en.events='Events';
words.zh.windowed='恢复窗口';words.en.windowed='Restore window';
words.zh.stateFilter='工作状态';words.en.stateFilter='Work state';words.zh.allStates='全部状态';words.en.allStates='All states';
words.zh.embedded='已嵌入 · 帧状态未知';
words.en.embedded='Embedded · frame status unknown';
words.zh.disconnect='断开显示';words.en.disconnect='Disconnect view';
words.zh.reconnect='重新连接';words.en.reconnect='Reconnect';
words.zh.choose='请选择';words.en.choose='Choose';
words.zh.nativeFrame='原生帧已更新';words.en.nativeFrame='Native frame updated';
words.zh.bindingNote='确认后在消费边界绑定当前全局版本；业务参数保持，目标改变须重审';words.en.bindingNote='Confirmation binds global versions at the consumption boundary; changed targets require review';
words.zh.scroll='滚轮滚动 · Shift平移 · Ctrl缩放';words.en.scroll='Wheel scrolls · Shift pans · Ctrl zooms';
const parameters={template_id:['模板','Template'],template_revision:['模板版本','Template revision'],order_id:['订单','Order'],quantity:['数量','Quantity'],due_sim_h:['交期 h','Due h'],priority:['优先级','Priority'],material_plan_id:['物料计划','Material plan'],arrival_rule:['到达规则','Arrival rule'],person_id:['人员','Person'],qualifications:['资格','Qualifications'],qualification_evidence_id:['资格证据','Qualification evidence'],parameter_template_id:['人员模板','Person template'],calendar_id:['日历','Calendar'],valid_until_h:['资格有效至 h','Qualified until h'],initial_f:['初始 F','Initial F'],arrival_location:['到岗位置','Arrival location'],scene_entity_id:['场景对象','Scene entity'],reason:['原因','Reason'],handover_policy:['交接策略','Handover policy'],safety_policy:['安全策略','Safety policy'],duration_h:['休息时长 h','Rest duration h'],repair_evidence_id:['维修证据','Repair evidence'],scope:['停止范围','Stop scope']};
function parameterLabel(key,language){return parameters[key]?.[language==='zh'?0:1]||key;}
const statusNames={VERIFIED:'fresh',STALE:'stale',STALE_CORRUPT:'warning',UNKNOWN:'unknown',AGE_UNKNOWN:'unknown'};
const feedbackWords={
  zh:{
    WAITING:'等待已核验计划',PLANNING:'排程中',AWAITING_VERIFICATION:'等待独立核验',AVAILABLE:'计划可用',FAILED:'排程或核验失败',UNAVAILABLE:'当前排程状态不可确认',HELD:'停止阶段 · 保留已核验计划',
    shown:'已核验计划',retained:'上一已核验计划',planAge:'计划源龄',obsAge:'业务观测源龄',obsSample:'业务观测源时刻',heartbeat:'进程心跳龄',sample:'计划源时刻',
    sent:'停止请求已发送',accept:'受理',PENDING:'等待',UNKNOWN:'UNKNOWN · 查询原 ID',ACCEPTED:'已持久受理',REJECTED:'已拒绝',
    save:'排空保存',SAVED:'已保存',UNCONFIRMED:'未确认',exit:'实际退出',pendingExit:'未观测',launcher:'启动器',restoreStop:'恢复原停止请求',restoreNote:'只恢复缺失的原请求，使用原 ID 和原参数。',
  },
  en:{
    WAITING:'Waiting for a verified plan',PLANNING:'Scheduling',AWAITING_VERIFICATION:'Awaiting independent verification',AVAILABLE:'Plan ready',FAILED:'Scheduling or verification failed',UNAVAILABLE:'Current scheduling status unconfirmed',HELD:'Stopping or ended · retaining the verified plan',
    shown:'Verified plan',retained:'Previous verified plan',planAge:'Plan source age',obsAge:'Observation age',obsSample:'Observation source time',heartbeat:'Worker heartbeat age',sample:'Plan source time',
    sent:'Stop request sent',accept:'Acceptance',PENDING:'Pending',UNKNOWN:'UNKNOWN · query original ID',ACCEPTED:'Durably accepted',REJECTED:'Rejected',
    save:'Drain and save',SAVED:'Saved',UNCONFIRMED:'Unconfirmed',exit:'Actual exit',pendingExit:'Unobserved',launcher:'Launcher',restoreStop:'Restore original stop',restoreNote:'Restore the missing request with its original ID and parameters.',
  },
};
const seconds=value=>Number.isFinite(value)?value.toFixed(1)+' s':'—';
const kindNames={ORDER_UPDATE:'updateOrder',ORDER_CREATE:'normal',PERSON_ARRIVE:'arrive',PERSON_DEPART:'depart',PERSON_ABSENT:'absent',PERSON_RETURN:'return',REST_REQUEST:'rest',DEVICE_FAIL:'failure',DEVICE_REPAIR:'repaired',ORDER_CANCEL:'cancelOrder',CLOSE_INPUT:'fence',STOP_REQUEST:'stop'};
const defaults={kind:'ORDER_CREATE',target_id:'',template_id:'SR-W1',quantity:'1',due_sim_h:'720',priority:'NORMAL',person_template:'P043-W1-v1',arrival_location:'F1',initial_f:'0.1',reason:'OPERATOR_REQUEST',duration_h:'0.1',repair_evidence_id:'',material_plan_id:'TEMPLATE-JIT-v1',time_rule:'IMMEDIATE',requested_sim_h:'0',expires_sim_h:'720'};
function Field({label,children,width=160}){return <label className="field" style={{width}}><span>{label}</span>{children}</label>}
function Button({children,onClick,disabled,className='',title,...props}){return <button type="button" className={className} onClick={onClick} disabled={disabled} title={title} {...props}>{children}</button>}

function App(){
  const [language,setLanguage]=useState(savedContext.language||'zh'),[layout,setLayout]=useState(null),[view,setView]=useState({}),[native,setNative]=useState({}),[phase,setPhase]=useState('DISCONNECTED');
  const [form,setForm]=useState(savedContext.form||null),[drafts,setDrafts]=useState(savedContext.drafts||{}),[preview,setPreview]=useState(null),[selection,setSelection]=useState(savedContext.selection||null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[details,setDetails]=useState(!!savedContext.details),[menu,setMenu]=useState(null);
  const [stopQuery,setStopQuery]=useState(null);
  const [support,setSupport]=useState(null),[diagnostics,setDiagnostics]=useState(null),[checking,setChecking]=useState(false),[exampleAvailable,setExampleAvailable]=useState(false);
  const [eventsOpen,setEventsOpen]=useState(false);
  const sceneSelection=useRef(null),viewRef=useRef(view);viewRef.current=view;
  const openSupport=section=>{setSupport(section);rpc('overlay',{open:true}).catch(onError);};
  const closeSupport=()=>{setSupport(null);rpc('overlay',{open:false}).catch(onError);};
  const diagnose=(full=false)=>{setChecking(true);setDiagnostics(null);rpc('diagnostics',{full,backend:setup.backend}).catch(e=>{setChecking(false);onError(e);});};
  const [settings,setSettings]=useState(()=>navigationSettings(savedContext.settings||{}));
  const [setup,setSetup]=useState({variant:'SR-W1',products:1,method:'ADAPTIVE',backend:'isaac',simulation_rate:.01});
  const [portable,setPortable]=useState(null);
  const [camera,setCamera]=useState(savedContext.camera||'Overview');
  const [detached,setDetached]=useState(false);
  const menuTrigger=useRef(null),formTrigger=useRef(null);
  const restoreFocus=element=>requestAnimationFrame(()=>element?.isConnected&&element.focus());
  const viewRatio=useRef(savedContext.splitRatio||.5);
  const toggleMenu=(name,event)=>{menuTrigger.current=event.currentTarget;setMenu(menu===name?null:name);};
  useEffect(()=>{if(menu)requestAnimationFrame(()=>document.querySelector('[role="menu"] button:not(:disabled)')?.focus());},[menu]);
  const t=key=>words[language][key]||key;
  useEffect(()=>{sessionStorage.setItem('p051-view',JSON.stringify({language,form,drafts,selection,details,settings,camera,splitRatio:layout?.split_ratio||viewRatio.current}))},[language,form,drafts,selection,details,settings,camera,layout?.split_ratio]);
  const onError=e=>{setError(e.message||String(e));setBusy(false);};
  useEffect(()=>{
    let alive=true;
    if(!window.qt?.webChannelTransport){setError('NATIVE_BRIDGE_UNAVAILABLE');return;}
    new window.QWebChannel(window.qt.webChannelTransport,c=>{
      nativeBridge=c.objects.workbench;calls.splice(0).forEach(run=>run());
      nativeBridge.event.connect(raw=>{if(!alive)return;const e=JSON.parse(raw);
        if(e.kind==='layout')setLayout(e.data);
        if(e.kind==='export_complete')window.dispatchEvent(new CustomEvent('hrc-export-complete',{detail:e.data}));
        if(e.kind==='diagnostics'){setDiagnostics(e.data);setChecking(false);}
        if(e.kind==='projection')setView(old=>{if(e.data.rows_mode!=='upsert')return e.data;const rows=new Map((old.rows||[]).map(r=>[r.row_id,r]));for(const key of e.data.row_deletes||[])rows.delete(key);for(const row of e.data.rows||[])rows.set(row.row_id,row);return {...e.data,rows:[...rows.values()]};});
        if(e.kind==='status'){setPhase(e.data.phase);setNative(e.data);setCamera(old=>viewCamera(e.data.scene?.last_command,old));setDetached(!!e.data.detached);const s=e.data.scene?.selection;if(s&&s.sequence!==sceneSelection.current){sceneSelection.current=s.sequence;if(s.entity_ids?.length)setSelection(old=>rowForEntity(viewRef.current.rows,s.entity_ids,old)||old);}}
        if(e.kind==='session_reset'){setPreview(null);setSelection(null);setNative({});setEventsOpen(false);sceneSelection.current=null;setStopQuery(null);setForm(null);setDetails(false);setBusy(false);rpc('layout',{form_open:false}).catch(onError);}
        if(e.kind==='error')onError(e.data.error);
        if(e.kind==='preview'){setPreview(e.data);setBusy(false);}
        if(e.kind==='submit'){setPreview(null);setBusy(false);setError('');}
        if(e.kind==='launched'){setBusy(false);setForm(null);rpc('layout',{form_open:false}).catch(onError);}
      });
      rpc('initialize').then(r=>{
        setLayout(r.layout);setLanguage(r.language);setPhase(r.phase);setPortable(r.portable);setExampleAvailable(r.example_available);if(savedContext.splitRatio)rpc('split',{ratio:savedContext.splitRatio}).then(setLayout).catch(onError);
        setChecking(true);rpc('diagnostics',{backend:'isaac'}).catch(e=>{setChecking(false);onError(e);});
        // An unavailable Isaac environment stays explicit; never silently switch to CPU.
        rpc('layout',{form_open:!!savedContext.form||!!savedContext.details}).catch(onError);
      }).catch(onError);
    });return()=>{alive=false};
  },[]);
  const openForm=(kind,priority)=>{setEventsOpen(false);formTrigger.current=menu?menuTrigger.current:document.activeElement;setForm(kind);setPreview(null);setError('');setMenu(null);if(priority)setDrafts(s=>({...s,[kind]:{...defaults,...s[kind],priority}}));rpc('layout',{form_open:true}).catch(onError);};
  const closeForm=()=>{setForm(null);setPreview(null);rpc('layout',{form_open:false}).catch(onError);restoreFocus(formTrigger.current);};
  const keyboard=e=>{
    if(e.key==='Escape'&&(menu||form)){e.preventDefault();e.stopPropagation();if(menu){setMenu(null);restoreFocus(menuTrigger.current);}else closeForm();return;}
    if(menu&&['ArrowDown','ArrowUp','Home','End'].includes(e.key)){const items=[...document.querySelectorAll('[role="menu"] button:not(:disabled)')];if(!items.length)return;e.preventDefault();const i=items.indexOf(document.activeElement),next=e.key==='Home'?0:e.key==='End'?items.length-1:(i+(e.key==='ArrowDown'?1:-1)+items.length)%items.length;items[next].focus();}
  };
  const d={...defaults,...drafts[form],kind:form};
  const change=(key,value)=>{setDrafts(s=>({...s,[form]:{...defaults,...s[form],[key]:value}}));setPreview(null);};
  const targetOptions=Object.keys(view.catalog?.objects||{});
  const field=(key,label,type='text',width=160)=> <Field key={key} label={t(label)} width={width}><input value={d[key]} type={type} onChange={e=>change(key,e.target.value)} step="any" list={key==='target_id'?'known-targets':undefined} required/></Field>;
  const select=(key,label,options,width=160)=><Field key={key} label={t(label)} width={width}><select value={d[key]} onChange={e=>change(key,e.target.value)}>{options.map(([v,text])=><option key={v} value={v}>{text}</option>)}</select></Field>;
  const review=e=>{e.preventDefault();setError('');setBusy(true);try{const payload=makePayload(form,d);rpc('preview',{kind:form,target_id:d.target_id,payload,time_rule:d.time_rule,requested_sim_h:Number(d.requested_sim_h),expires_sim_h:Number(d.expires_sim_h)}).catch(onError);}catch(e){onError(e);}};
  const commit=()=>{setBusy(true);rpc('submit',preview).catch(onError);};
  const picked=restoreSelection(view.rows||[],selection);
  const toggleDetails=value=>{setEventsOpen(false);setDetails(value);rpc('layout',{form_open:!!form||value}).catch(onError);};
  const choose=row=>{setSelection(row);const entity=selectedEntity(row,native.scene?.entities);if(entity&&native.native_available&&native.scene?.entities?.some(x=>x.id===entity&&x.paths?.length&&x.visible!==false))rpc('locate',{entity_id:entity}).catch(onError);};
  const showEvents=()=>{setEventsOpen(true);setDetails(false);setForm(null);rpc('layout',{form_open:true}).catch(onError);};
  const closeEvents=()=>{setEventsOpen(false);rpc('layout',{form_open:false}).catch(onError);};
  const canWrite=!!view.writable&&!detached&&!native.observation_stale&&!native.stop_holding;
  useEffect(()=>{if(form==='REST_REQUEST'){setForm(null);setPreview(null);}},[form]);
  const nativePlan=native.frame?.full_schedule;
  const planFailure=view.full_schedule?.failure;
  const blockedLabel=language==='zh'?'排程受阻 · 等待恢复':'Plan blocked · awaiting recovery';
  const fullPlanning=['RUNNING','CONNECTING'].includes(phase)&&nativePlan?.planning===true;
  const feedback=detached?null:native.waiting_feedback;
  const stop=native.stop_feedback, w=feedbackWords[language];
  const queriedStop=stopQuery&&(stop||stopQuery);
  const queryOriginal=()=>rpc('query').then(({stop,...receipts})=>{
    setView(s=>({...s,...receipts}));
    if(stop){setStopQuery(stop);toggleDetails(true);}
  }).catch(onError);
  const shownVersion=view.verified_full_schedule?.version;
  const previousPlan=shownVersion!=null&&feedback?.phase&&feedback.phase!=='AVAILABLE';
  const observationStatus=view.status==='VERIFIED'&&native.observation_stale?'STALE':view.status;
  const feedbackStage=feedback?.phase&&w[feedback.phase];
  const stageLabel=feedbackStage
    ? [feedbackStage,feedback.wait_s==null?null:seconds(feedback.wait_s),feedback.candidate_version==null?null:t('candidate')+' v'+feedback.candidate_version].filter(Boolean).join(' · ')
    : planFailure?(phase==='RUNNING'?blockedLabel:phase+' · '+blockedLabel):fullPlanning?(language==='zh'?'排程中 · 模拟时钟暂停':'Planning · simulation paused'):phase;
  const stopLabel=stop&&[
    w.sent, w.accept+' '+w[stop.acceptance], w.save+' '+w[stop.save],
    w.exit+' '+(stop.worker_exit??w.pendingExit),
    stop.launcher_exit!=null&&stop.launcher_exit!==stop.worker_exit?w.launcher+' '+stop.launcher_exit:null,
  ].filter(Boolean).join(' · ');
  const runBusy=(['PREPARING','CONNECTING','RUNNING','STOPPING','STOPPED','STOP_BLOCKED','DISPLAY_UNKNOWN'].includes(phase)&&native.worker_exit==null)||!!native.native;
  const p=layout?.plots,profile=layout?.profile||'compact';
  const labelWidth=layout?.label_width||210;
  const expanded=!!form||details||eventsOpen||!!error||!!menu;
  useEffect(()=>{rpc('layout',{form_open:expanded}).catch(()=>{});},[expanded]);
  const chrome=layout?.chrome;
  const pad=chrome?.pad??12;
  const mast=chrome?.mast??36,identityHeight=chrome?.identity??24,gap=chrome?.gap??4;
  const actionsY=pad+mast+identityHeight+2*gap;
  const auxHeight=chrome?.aux??(expanded?184:52);
  const footerHeight=chrome?.footer??24;
  const auxY=chrome?.aux_y??((layout?.client[1]||768)-pad-footerHeight-gap-auxHeight);
  const menuPos={position:'fixed',left:pad,right:pad,top:auxY,height:auxHeight,display:'flex',alignItems:'flex-start',gap:8,flexWrap:'wrap',padding:16,zIndex:120};
  const ratio=layout?.split_ratio??.5;const preset=Math.abs(ratio-.5)<.005?'operate':Math.abs(ratio-.58)<.005?'demonstrate':Math.abs(ratio-.42)<.005?'analyze':'custom';
  const historical=phase==='SAVED_READ_ONLY',progress=archiveProgress(view),freshStart=phase==='DISCONNECTED'&&!view.envelope;
  const hasNative=!!native.native_available&&!detached;
  const phaseText=historical?(language==='zh'?`历史存档 · 只读 · ${progress==null?'正在读取':progress<100?'读取 '+progress+'%':'已读取'}`:`Archive · read only · ${progress==null?'Loading':progress<100?'Loading '+progress+'%':'Loaded'}`):freshStart?(language==='zh'?'完整生产仿真 · Isaac 与甘特联动':'Production simulation · Isaac + timeline'):`${t(statusNames[observationStatus]||'disconnected')} · ${stageLabel}`;
  return <main style={{'--support-left':p?(p[1].x-labelWidth)+'px':'52%'}} lang={language==='zh'?'zh-CN':'en'} className={profile+(settings.comfortable!==false?' comfortable':'')+(layout?.focus_gantt?' focused':'')+(freshStart?(form?' fresh-setup':' fresh-start'):'')} onKeyDown={keyboard} onClick={()=>menu&&setMenu(null)}>
    <header style={{left:pad,top:pad,right:pad,height:mast}}><div><h1>{t('title')}</h1><span className="phase" data-plan-phase={feedback?.phase}>{phaseText}</span></div><div className="clock">{Number.isFinite(view.envelope?.sampled_sim_h)?view.envelope.sampled_sim_h.toFixed(4)+' h':'—'}<small>{t('time')} · {view.clock?.simulation_rate??'—'} h/s</small></div></header>
    <div className="identity-strip" style={{left:pad,right:pad,top:pad+mast+gap,height:identityHeight}}>
      <Summary view={view} language={language} onDetails={()=>toggleDetails(true)}/>
      {stopLabel&&<span className="stop-progress" title={stop.request_id}>{stopLabel}</span>}
      <span className="plan-identity" data-plan-version={shownVersion}>
        {previousPlan?w.retained:w.shown} {shownVersion==null?'—':'v'+shownVersion}
        {shownVersion!=null&&feedback&&<> · {feedback.plan_age_s==null?w.sample+' '+(feedback.plan_sample_h?.toFixed(2)??'—')+' h':w.planAge+' '+seconds(feedback.plan_age_s)}</>}
        {phase==='SAVED_READ_ONLY'
          ? ' · '+w.obsSample+' '+(view.envelope?.sampled_sim_h?.toFixed(2)??'—')+' h'
          : ' · '+w.obsAge+' '+seconds(native.source_age_s)}
        {feedback?.heartbeat_age_s!=null&&' · '+w.heartbeat+' '+seconds(feedback.heartbeat_age_s)}
      </span>
    </div>
    <nav style={{left:pad,right:pad,top:actionsY,height:chrome?.actions??36}}>
      <Button onClick={()=>openForm('setup')} disabled={runBusy}>{t('start')}</Button><Button onClick={()=>rpc('open').catch(onError)} disabled={runBusy}>{t('open')}</Button>
      <Button onClick={()=>rpc('connection',{detached:!detached}).then(r=>setDetached(r.detached)).catch(onError)}>{t(detached?'reconnect':'disconnect')}</Button>
      <Button className="primary" onClick={()=>openForm('ORDER_CREATE','NORMAL')} disabled={!canWrite}>{t('normal')}</Button><Button onClick={()=>openForm('ORDER_CREATE','URGENT')} disabled={!canWrite}>{t('urgent')}</Button>
      <div className="menu-root"><Button onClick={e=>toggleMenu('people',e)} aria-haspopup="menu" aria-expanded={menu==='people'} disabled={!canWrite}>{t('people')}</Button>{menu==='people'&&<div className="menu" role="menu" style={menuPos}>{['PERSON_ARRIVE','PERSON_DEPART','PERSON_ABSENT','PERSON_RETURN','REST_REQUEST'].map(k=><button role="menuitem" key={k} disabled={k==='REST_REQUEST'} title={k==='REST_REQUEST'?(language==='zh'?'手动休息尚未实现；自动排程休息不受影响':'Manual rest is unavailable; scheduled rest remains active'):undefined} onClick={()=>openForm(k)}>{t(kindNames[k])}{k==='REST_REQUEST'?(language==='zh'?'（未实现）':' (unavailable)'):''}</button>)}</div>}</div>
      <div className="menu-root"><Button onClick={e=>toggleMenu('events',e)} aria-haspopup="menu" aria-expanded={menu==='events'} disabled={!canWrite}>{t('more')}</Button>{menu==='events'&&<div className="menu" role="menu" style={menuPos}>{['ORDER_UPDATE','DEVICE_FAIL','DEVICE_REPAIR','ORDER_CANCEL'].map(k=><button role="menuitem" key={k} disabled={k==='REST_REQUEST'} title={k==='REST_REQUEST'?(language==='zh'?'手动休息尚未实现；自动排程休息不受影响':'Manual rest is unavailable; scheduled rest remains active'):undefined} onClick={()=>openForm(k)}>{t(kindNames[k])}{k==='REST_REQUEST'?(language==='zh'?'（未实现）':' (unavailable)'):''}</button>)}</div>}</div>
      <Button onClick={()=>openForm('CLOSE_INPUT')} disabled={!canWrite}>{t('close')}</Button><Button className="stop" onClick={()=>openForm('STOP_REQUEST')} disabled={!runBusy||(native.stop_holding&&!native.stop_recoverable)}>{native.stop_recoverable?w.restoreStop:t('stop')}</Button>
      <select aria-label={language==='zh'?'双图布局':'Dual-view layout'} value={preset} onChange={e=>rpc('view_preset',{preset:e.target.value}).then(setLayout).catch(onError)}>{preset==='custom'&&<option value='custom' disabled>{language==='zh'?'自定义比例':'Custom split'}</option>}<option value='operate'>{language==='zh'?'双图运行':'Operate'}</option><option value='demonstrate'>{language==='zh'?'场景讲解':'Demonstrate'}</option><option value='analyze'>{language==='zh'?'排程分析':'Analyze'}</option></select><Button onClick={()=>{rpc('restore').catch(onError)}}>{t('restore')}</Button><Button onClick={()=>{const l=language==='zh'?'en':'zh';setLanguage(l);rpc('language',{language:l}).catch(onError)}}>{t('language')}</Button><Button onClick={()=>openSupport('diagnostics')}>{language==='zh'?'自检':'Diagnostics'}</Button><Button onClick={()=>openSupport('help')}>{language==='zh'?'帮助':'Help'}</Button>
    </nav>
    {p&&!freshStart&&<>
      {(layout?.focus_gantt?[1]:[0,1]).map(n=>{const rect=p[n],title=24,toolbar=64;return <div key={n} className="panel-title" style={{left:rect.x-(n?labelWidth:0),top:rect.y-title-toolbar,width:rect.width+(n?labelWidth:0),height:title}}><strong>{n?(historical?(language==='zh'?'历史计划与执行':'Archived plan & execution'):t('gantt')):t('native')+' · '+(language==='zh'?'生产场景':'Production scene')}</strong><Button onClick={()=>rpc('fullscreen').catch(onError)}>{t(native.fullscreen?'windowed':'maximize')}</Button></div>})}
      {!layout?.focus_gantt&&<>
      <SceneTools view={view} native={native} picked={picked} language={language} rpc={rpc} onError={onError} camera={camera} setCamera={setCamera} style={{left:p[0].x,top:p[0].y-64,width:p[0].width,height:64}}/>
      {!native.native&&<SceneEmpty phase={phase} backend={view.backend} native={native} language={language} onSettings={()=>openSupport('diagnostics')} onStart={runBusy?undefined:()=>openForm('setup')} style={{left:p[0].x,top:p[0].y,width:p[0].width,height:p[0].height}}/>}
      <ContextStrip view={view} native={native} phase={phase} language={language} onEvents={showEvents} style={{left:p[0].x,top:p[0].y+p[0].height,width:p[0].width,height:24}}/>
      <div className="split-handle vertical" style={{left:p[0].x+p[0].width,top:p[0].y-(profile==='wide'?96:88),width:8,height:p[0].height+(profile==='wide'?120:112)}} role="separator" aria-label={t('restore')} tabIndex="0" onPointerDown={e=>e.currentTarget.setPointerCapture(e.pointerId)} onPointerMove={e=>{if(!e.currentTarget.hasPointerCapture(e.pointerId))return;rpc('split',{ratio:Math.max(.1,Math.min(.9,(e.clientX-p[0].x)/(p[0].width+p[1].width+labelWidth)))}).then(setLayout).catch(onError)}} onKeyDown={e=>{if(['ArrowRight','ArrowLeft'].includes(e.key))rpc('split',{ratio:Math.max(.1,Math.min(.9,(layout.split_ratio||.5)+(e.key==='ArrowRight'?.01:-.01)))}).then(setLayout).catch(onError)}}/>
      </>}
      <Timeline phase={planFailure?'PLAN_BLOCKED':phase} waitingForPlan={shownVersion==null&&['WAITING','PLANNING','AWAITING_VERIFICATION'].includes(feedback?.phase)} plot={p[1]} profile={profile} labelWidth={labelWidth} view={view} t={t} selection={picked} onSelect={choose} settings={settings} setSettings={setSettings} onError={onError} rpc={rpc} language={language}/>
    </>}
    <section className="aux" style={{left:pad,right:pad,top:auxY,height:auxHeight}}>
      {form==='setup'?<Setup language={language} setup={setup} setSetup={setSetup} portable={portable} busy={busy} onSubmit={e=>{e.preventDefault();setBusy(true);setError('');rpc('start',setup).catch(onError)}} onClose={closeForm} onDiagnose={()=>openSupport('diagnostics')} onSettings={()=>rpc('portable_settings').then(next=>{setPortable(next);setDiagnostics(null);}).catch(onError)}/>:form?<>
        {preview?<div className="preview-line"><div><strong>{t('actualParams')} · {t(preview.kind==='ORDER_CREATE'&&preview.payload.priority==='URGENT'?'urgent':kindNames[preview.kind])}</strong><div className="parameter-summary">{Object.entries(preview.payload).filter(([k])=>!k.includes('sha256')&&k!=='scene_reference').map(([k,v])=><span key={k}>{parameterLabel(k,language)}: {typeof v==='object'?JSON.stringify(v):String(v)}</span>)}</div><small>{preview.recovery?w.restoreNote:t('bindingNote')}</small><small>{preview.target_id} · {preview.time_rule} · #{preview.client_sequence} · {preview.request_id}</small></div><Button className="primary" disabled={busy} onClick={commit}>{t('confirm')}</Button><Button onClick={()=>setPreview(null)}>{t('cancel')}</Button></div>:
        <form className="form-line" onSubmit={review}>
          {form==='ORDER_CREATE'?<>{select('template_id','template',[['SR-W1','SR-W1'],['SR-W2','SR-W2']],200)}{field('quantity','quantity','number',96)}{field('due_sim_h','due','number',160)}{select('priority','priority',[['NORMAL',t('normalOption')],['URGENT',t('urgentOption')]],136)}{field('target_id','target','text',220)}</>:
          !['CLOSE_INPUT','STOP_REQUEST'].includes(form)&&<>{field('target_id','target','text',220)}
            {form==='PERSON_ARRIVE'&&<>{select('person_template','personTemplate',(view.ui_options?.person_templates||['P043-W1-v1']).map(x=>[x,x]),240)}{field('initial_f','initial','number',96)}</>}
            {['PERSON_ARRIVE','PERSON_RETURN'].includes(form)&&select('arrival_location','position',(view.ui_options?.locations||['F1','PRE','Q1','OUT1']).map(x=>[x,x]),160)}
            {form==='ORDER_UPDATE'&&<>{field('due_sim_h','due','number',160)}{select('priority','priority',[['NORMAL',t('normalOption')],['URGENT',t('urgentOption')]],136)}</>}
            {['PERSON_DEPART','PERSON_ABSENT','DEVICE_FAIL','ORDER_CANCEL'].includes(form)&&field('reason','reason','text',240)}
            {form==='REST_REQUEST'&&field('duration_h','duration','number',180)}
            {form==='DEVICE_REPAIR'&&select('repair_evidence_id','repair',[['',t('choose')],...(view.ui_options?.repair_evidence||[]).map(x=>[x,x])],260)}
          </>}
          {['CLOSE_INPUT','STOP_REQUEST'].includes(form)&&<p className="confirm-info">{t(kindNames[form])} · {t('safe')}</p>}
          <button className="primary" disabled={busy||(!canWrite&&form!=='STOP_REQUEST')}>{busy?t('pending'):t('preview')}</button><Button onClick={closeForm}>{t('cancel')}</Button>
          {form==='ORDER_CREATE'&&select('material_plan_id','material',[['TEMPLATE-JIT-v1',t('jit')],['TEMPLATE-DELAY-1H-v1',t('delay')]],180)}
          {select('time_rule','timeRule',[['IMMEDIATE',t('immediate')],['AT_SIM_H',t('atTime')]],200)}{d.time_rule==='AT_SIM_H'&&field('requested_sim_h','at','number',180)}{field('expires_sim_h','expires','number',180)}
        </form>}
      </>:<div className="detail-line"><Button onClick={()=>toggleDetails(!details)}>{t('detail')}</Button><span>{picked?`${picked.display_name||picked[language==='zh'?'operation_name_zh':'operation_name_en']||picked.operation_id||picked.resource_id||picked.person_id||''} · ${t(picked.schedule_state?.toLowerCase())}`:t('noSelection')}</span><span className="legend"><i className="solid"/>{t('actual')} <i/>{t(view.full_schedule?'planned':'committed')} {!view.full_schedule&&<><i className="dashed"/>{t('tentative')}</>}</span><Button onClick={queryOriginal}>{t('query')}</Button><Button onClick={()=>rpc('evidence').catch(onError)}>{t('evidence')}</Button></div>}

    </section>
    {details&&!form&&<Inspector view={view} picked={picked} language={language} t={t} stop={queriedStop} onClose={()=>toggleDetails(false)} onQuery={queryOriginal} onEvidence={()=>rpc('evidence').catch(onError)} style={{left:pad,right:pad,top:auxY,height:auxHeight}}/>}
    {freshStart&&!form&&<Welcome language={language} exampleAvailable={exampleAvailable} onExample={()=>rpc('example').catch(onError)} onStart={()=>openForm('setup')} onOpen={()=>rpc('open').catch(onError)} onHelp={()=>openSupport('help')} onDiagnose={()=>openSupport('diagnostics')}/>}
    <datalist id="known-targets">{targetOptions.map(id=><option key={id} value={id}/>)}</datalist>
    {support&&<Support section={support} language={language} diagnostics={diagnostics} checking={checking} onCheck={diagnose} onClose={closeSupport} onExport={()=>rpc('diagnostic_export').catch(onError)} onGuide={()=>rpc('help').catch(onError)}/>}
    {eventsOpen&&<Events view={view} native={native} language={language} onTarget={ids=>{const row=rowForEntity(view.rows,ids,picked);if(row)choose(row);}} onClose={closeEvents} style={{left:pad,right:pad,top:auxY,height:auxHeight}}/>}
    {error&&<ErrorBanner style={{top:auxY,height:auxHeight}} error={error} language={language} onClose={()=>setError('')} onDiagnose={()=>{setError('');openSupport('diagnostics');diagnose(false);}}/>}
    <footer style={{left:pad,right:pad,bottom:pad,height:footerHeight}}><span>{historical?(language==='zh'?'历史记录':'Historical record'):view.status==='VERIFIED'?t('fresh'):t(statusNames[view.status]||'unknown')} · {view.writable?t('form'):t('readonly')} · {view.envelope?.observation_id||'—'} · {t('scroll')}</span><div className="range-controls"><button onClick={()=>setSettings(s=>({...s,comfortable:s.comfortable===false}))}>{settings.comfortable===false?(language==='zh'?'舒适字号':'Larger text'):(language==='zh'?'紧凑字号':'Compact text')}</button><label>{t('begin')} <input aria-label={t('begin')} type="number" step="0.1" value={settings.start} onChange={e=>setSettings(s=>({...s,manual:true,follow:false,start:Math.max(0,Number(e.target.value))}))}/></label><label>{t('span')} <input aria-label={t('span')} type="number" min="0.002" step="0.1" value={settings.span} onChange={e=>setSettings(s=>({...s,manual:true,scaleStep:null,span:Math.max(.002,Number(e.target.value))}))}/></label></div></footer>
  </main>
}
createRoot(document.getElementById('root')).render(<App/>);
