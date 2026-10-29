import React,{useEffect,useMemo,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import Timeline from './Timeline.jsx';
import {navigationSettings,rangeOf,timeLabel} from './gantt-model.mjs';
import {makePayload} from './model.mjs';
import './style.css';

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
const kindNames={ORDER_UPDATE:'updateOrder',ORDER_CREATE:'normal',PERSON_ARRIVE:'arrive',PERSON_DEPART:'depart',PERSON_ABSENT:'absent',PERSON_RETURN:'return',REST_REQUEST:'rest',DEVICE_FAIL:'failure',DEVICE_REPAIR:'repaired',ORDER_CANCEL:'cancelOrder',CLOSE_INPUT:'fence',STOP_REQUEST:'stop'};
const defaults={kind:'ORDER_CREATE',target_id:'',template_id:'SR-W1',quantity:'1',due_sim_h:'720',priority:'NORMAL',person_template:'P043-W1-v1',arrival_location:'F1',initial_f:'0.1',reason:'OPERATOR_REQUEST',duration_h:'0.1',repair_evidence_id:'',material_plan_id:'TEMPLATE-JIT-v1',time_rule:'IMMEDIATE',requested_sim_h:'0',expires_sim_h:'720'};
function Field({label,children,width=160}){return <label className="field" style={{width}}><span>{label}</span>{children}</label>}
function Button({children,onClick,disabled,className='',title}){return <button type="button" className={className} onClick={onClick} disabled={disabled} title={title}>{children}</button>}

function App(){
  const [language,setLanguage]=useState(savedContext.language||'zh'),[layout,setLayout]=useState(null),[view,setView]=useState({}),[native,setNative]=useState({}),[phase,setPhase]=useState('DISCONNECTED');
  const [form,setForm]=useState(savedContext.form||null),[drafts,setDrafts]=useState(savedContext.drafts||{}),[preview,setPreview]=useState(null),[selection,setSelection]=useState(savedContext.selection||null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[details,setDetails]=useState(!!savedContext.details),[menu,setMenu]=useState(null);
  const [settings,setSettings]=useState(()=>navigationSettings(savedContext.settings||{}));
  const [setup,setSetup]=useState({variant:'SR-W1',products:1,method:'ADAPTIVE',backend:'isaac',simulation_rate:.01});
  const [camera,setCamera]=useState(savedContext.camera||'Overview');
  const [detached,setDetached]=useState(false);
  const t=key=>words[language][key]||key;
  useEffect(()=>{sessionStorage.setItem('p051-view',JSON.stringify({language,form,drafts,selection,details,settings,camera}))},[language,form,drafts,selection,details,settings,camera]);
  const onError=e=>{setError(e.message||String(e));setBusy(false);};
  useEffect(()=>{
    let alive=true;
    if(!window.qt?.webChannelTransport){setError('NATIVE_BRIDGE_UNAVAILABLE');return;}
    new window.QWebChannel(window.qt.webChannelTransport,c=>{
      nativeBridge=c.objects.workbench;calls.splice(0).forEach(run=>run());
      nativeBridge.event.connect(raw=>{if(!alive)return;const e=JSON.parse(raw);
        if(e.kind==='layout')setLayout(e.data);
        if(e.kind==='projection')setView(old=>{if(e.data.rows_mode!=='upsert')return e.data;const rows=new Map((old.rows||[]).map(r=>[r.row_id,r]));for(const key of e.data.row_deletes||[])rows.delete(key);for(const row of e.data.rows||[])rows.set(row.row_id,row);return {...e.data,rows:[...rows.values()]};});
        if(e.kind==='status'){setPhase(e.data.phase);setNative(e.data);setDetached(!!e.data.detached);setView(v=>({...v,source_age_s:e.data.source_age_s??v.source_age_s}));}
        if(e.kind==='error')onError(e.data.error);
        if(e.kind==='preview'){setPreview(e.data);setBusy(false);}
        if(e.kind==='submit'){setPreview(null);setBusy(false);setError('');}
        if(e.kind==='launched'){setBusy(false);setForm(null);rpc('layout',{form_open:false}).catch(onError);}
      });
      rpc('initialize').then(r=>{setLayout(r.layout);setLanguage(r.language);setPhase(r.phase);rpc('layout',{form_open:!!savedContext.form||!!savedContext.details}).catch(onError);}).catch(onError);
    });return()=>{alive=false};
  },[]);
  const openForm=(kind,priority)=>{setForm(kind);setPreview(null);setError('');setMenu(null);if(priority)setDrafts(s=>({...s,[kind]:{...defaults,...s[kind],priority}}));rpc('layout',{form_open:true}).catch(onError);};
  const closeForm=()=>{setForm(null);setPreview(null);rpc('layout',{form_open:false}).catch(onError);};
  const d={...defaults,...drafts[form],kind:form};
  const change=(key,value)=>{setDrafts(s=>({...s,[form]:{...defaults,...s[form],[key]:value}}));setPreview(null);};
  const field=(key,label,type='text',width=160)=> <Field key={key} label={t(label)} width={width}><input value={d[key]} type={type} onChange={e=>change(key,e.target.value)} step="any" required/></Field>;
  const select=(key,label,options,width=160)=><Field key={key} label={t(label)} width={width}><select value={d[key]} onChange={e=>change(key,e.target.value)}>{options.map(([v,text])=><option key={v} value={v}>{text}</option>)}</select></Field>;
  const review=e=>{e.preventDefault();setError('');setBusy(true);try{const payload=makePayload(form,d);rpc('preview',{kind:form,target_id:d.target_id,payload,time_rule:d.time_rule,requested_sim_h:Number(d.requested_sim_h),expires_sim_h:Number(d.expires_sim_h)}).catch(onError);}catch(e){onError(e);}};
  const commit=()=>{setBusy(true);rpc('submit',preview).catch(onError);};
  const picked=selection&&view.rows?.find(r=>r.row_id===selection.row_id)||selection;
  const toggleDetails=value=>{setDetails(value);rpc('layout',{form_open:!!form||value}).catch(onError);};
  const choose=row=>{setSelection(row);};
  const canWrite=!!view.writable&&!detached;
  useEffect(()=>{if(form==='REST_REQUEST'){setForm(null);setPreview(null);}},[form]);
  const nativePlan=native.frame?.full_schedule;
  const planFailure=view.full_schedule?.failure;
  const blockedLabel=language==='zh'?'排程受阻 · 等待恢复':'Plan blocked · awaiting recovery';
  const fullPlanning=['RUNNING','CONNECTING'].includes(phase)&&nativePlan?.planning===true;
  const runBusy=(['PREPARING','CONNECTING','RUNNING','STOPPING','STOPPED','STOP_BLOCKED','DISPLAY_UNKNOWN'].includes(phase)&&native.worker_exit==null)||!!native.native;
  const p=layout?.plots,profile=layout?.profile||'compact';
  const labelWidth=layout?.label_width||210;
  const expanded=!!form||details;
  const pad=profile==='wide'||profile==='narrow'?16:12;
  const mast=profile==='wide'?64:profile==='narrow'?44:40,identityHeight=profile==='wide'?32:profile==='narrow'?28:24,gap=profile==='wide'||profile==='narrow'?8:(expanded?4:6);
  const actionsY=pad+mast+identityHeight+2*gap;
  const auxHeight=profile==='wide'?(expanded?200:72):profile==='narrow'?48:(expanded?144:32);
  const footerHeight=profile==='wide'?32:profile==='narrow'?24:20;
  const auxY=(layout?.client[1]||768)-pad-footerHeight-gap-auxHeight;
  return <main lang={language==='zh'?'zh-CN':'en'} className={profile} onClick={()=>menu&&setMenu(null)}>
    <header style={{left:pad,top:pad,right:pad,height:mast}}><div><h1>{t('title')}</h1><span className="phase">{t(statusNames[view.status]||'disconnected')} · {planFailure?(phase==='RUNNING'?blockedLabel:phase+' · '+blockedLabel):fullPlanning?(language==='zh'?'排程中 · 模拟时钟暂停':'Planning · simulation paused'):phase}</span></div><div className="clock">{Number.isFinite(view.envelope?.sampled_sim_h)?view.envelope.sampled_sim_h.toFixed(4)+' h':'—'}<small>{t('time')} · {view.clock?.simulation_rate??'—'} h/s</small></div></header>
    <div className="identity-strip" style={{left:pad,right:pad,top:pad+mast+gap,height:identityHeight}}><span>{view.envelope?.run_id||t('waiting')}</span><span>{view.backend||'—'} · {language==='zh'?'目录':'Catalog'} v{view.envelope?.catalog_version??'—'} · {language==='zh'?'完整计划':'Full plan'} v{view.full_schedule?.version??'—'} · {t('age')} {view.source_age_s==null?'—':view.source_age_s.toFixed(1)+'s'} · {t('selection')}: {picked?.work_number||'—'}</span></div>
    <nav style={{left:pad,right:pad,top:actionsY,height:44}}>
      <Button onClick={()=>openForm('setup')} disabled={runBusy}>{t('start')}</Button><Button onClick={()=>rpc('open').catch(onError)} disabled={runBusy}>{t('open')}</Button>
      <Button onClick={()=>rpc('connection',{detached:!detached}).then(r=>setDetached(r.detached)).catch(onError)}>{t(detached?'reconnect':'disconnect')}</Button>
      <Button className="primary" onClick={()=>openForm('ORDER_CREATE','NORMAL')} disabled={!canWrite}>{t('normal')}</Button><Button onClick={()=>openForm('ORDER_CREATE','URGENT')} disabled={!canWrite}>{t('urgent')}</Button>
      <div className="menu-root"><Button onClick={()=>setMenu(menu==='people'?null:'people')} disabled={!canWrite}>{t('people')}</Button>{menu==='people'&&<div className="menu" role="menu">{['PERSON_ARRIVE','PERSON_DEPART','PERSON_ABSENT','PERSON_RETURN','REST_REQUEST'].map(k=><button role="menuitem" key={k} disabled={k==='REST_REQUEST'} title={k==='REST_REQUEST'?(language==='zh'?'手动休息尚未实现；自动排程休息不受影响':'Manual rest is unavailable; scheduled rest remains active'):undefined} onClick={()=>openForm(k)}>{t(kindNames[k])}{k==='REST_REQUEST'?(language==='zh'?'（未实现）':' (unavailable)'):''}</button>)}</div>}</div>
      <div className="menu-root"><Button onClick={()=>setMenu(menu==='events'?null:'events')} disabled={!canWrite}>{t('more')}</Button>{menu==='events'&&<div className="menu" role="menu">{['ORDER_UPDATE','DEVICE_FAIL','DEVICE_REPAIR','ORDER_CANCEL'].map(k=><button role="menuitem" key={k} disabled={k==='REST_REQUEST'} title={k==='REST_REQUEST'?(language==='zh'?'手动休息尚未实现；自动排程休息不受影响':'Manual rest is unavailable; scheduled rest remains active'):undefined} onClick={()=>openForm(k)}>{t(kindNames[k])}{k==='REST_REQUEST'?(language==='zh'?'（未实现）':' (unavailable)'):''}</button>)}</div>}</div>
      <Button onClick={()=>openForm('CLOSE_INPUT')} disabled={!canWrite}>{t('close')}</Button><Button className="stop" onClick={()=>openForm('STOP_REQUEST')} disabled={!runBusy}>{t('stop')}</Button>
      <Button onClick={()=>{rpc('restore').catch(onError)}}>{t('restore')}</Button><Button onClick={()=>{const l=language==='zh'?'en':'zh';setLanguage(l);rpc('language',{language:l}).catch(onError)}}>{t('language')}</Button>
    </nav>
    {p&&<>
      {[0,1].map(n=>{const rect=p[n],title=profile==='wide'?32:profile==='narrow'?28:24,toolbar=64;return <div key={n} className="panel-title" style={{left:rect.x-(n?labelWidth:0),top:rect.y-title-toolbar,width:rect.width+(n?labelWidth:0),height:title}}><strong>{n?t('gantt'):t('native')+' / '+t('readonly')}</strong><Button onClick={()=>rpc('fullscreen').catch(onError)}>{t(native.fullscreen?'windowed':'maximize')}</Button></div>})}
      <div className="native-tools" style={{left:p[0].x,top:p[0].y-64,width:p[0].width,height:64}}><label>{t('camera')} <select value={camera} onChange={e=>{setCamera(e.target.value);rpc('camera',{camera:e.target.value}).catch(onError)}}>{['Overview','Top','Supply','Equipment','Crossing','Finished','Gantry','F1','Fork','Test'].map(c=><option key={c}>{c}</option>)}</select></label><Button disabled={!picked} onClick={()=>rpc('locate',{entity_id:picked.product_id||picked.display_product_id||picked.resource_id||picked.person_id}).catch(onError)}>{t('locate')}</Button><span className="native-capsule">{language==='zh'?'模拟时刻':'Sim time'} {view.envelope?.sampled_sim_h?.toFixed(3)||'—'} h · {t(statusNames[view.status]||'unknown')} · {language==='zh'?'计划':'Plan'} v{view.full_schedule?.version??'—'}</span></div>

      {!native.native&&<div className="native-empty" style={{left:p[0].x,top:p[0].y,width:p[0].width,height:p[0].height}}>{t('disconnected')}<small>{t('future')}</small></div>}
      <div className="native-axis" style={{left:p[0].x,top:p[0].y+p[0].height,width:p[0].width,height:profile==='compact'?20:24}}>{t('nativeState')}: r{native.frame?.source_state_revision??'—'} · {t('age')} {native.frame?.age_s?.toFixed(1)??'—'}s · {t('gantt')}: r{view.envelope?.state_revision??'—'}</div>
      <div className="split-handle vertical" style={{left:p[0].x+p[0].width,top:p[0].y-(profile==='wide'?96:88),width:8,height:p[0].height+(profile==='wide'?120:112)}} role="separator" aria-label={t('restore')} tabIndex="0" onPointerDown={e=>e.currentTarget.setPointerCapture(e.pointerId)} onPointerMove={e=>{if(!e.currentTarget.hasPointerCapture(e.pointerId))return;rpc('split',{ratio:Math.max(.1,Math.min(.9,(e.clientX-p[0].x)/(p[0].width+p[1].width+labelWidth)))}).then(setLayout).catch(onError)}} onKeyDown={e=>{if(['ArrowRight','ArrowLeft'].includes(e.key))rpc('split',{ratio:Math.max(.1,Math.min(.9,(layout.split_ratio||.5)+(e.key==='ArrowRight'?.01:-.01)))}).then(setLayout).catch(onError)}}/>
      <Timeline phase={planFailure?'PLAN_BLOCKED':phase} plot={p[1]} profile={profile} labelWidth={labelWidth} view={view} t={t} selection={picked} onSelect={choose} settings={settings} setSettings={setSettings} onError={onError} rpc={rpc} language={language}/>
    </>}
    <section className="aux" style={{left:pad,right:pad,top:auxY,height:auxHeight}}>
      {form==='setup'?<form className="form-line" onSubmit={e=>{e.preventDefault();setBusy(true);rpc('start',setup).catch(onError)}}>
        <Field label={t('variant')} width={180}><select value={setup.variant} onChange={e=>setSetup(s=>({...s,variant:e.target.value}))}><option>SR-W1</option><option>SR-W2</option></select></Field>
        <Field label={t('products')} width={100}><input type="number" min="1" max="3" value={setup.products} onChange={e=>setSetup(s=>({...s,products:Number(e.target.value)}))}/></Field>
        <Field label={t('method')} width={160}><select value={setup.method} onChange={e=>setSetup(s=>({...s,method:e.target.value}))}><option value="ADAPTIVE">{language==='zh'?'完整计划 · 固定工时':'Full plan · fixed hours'}</option></select></Field>
        <Field label={t('backend')} width={180}><select value={setup.backend} onChange={e=>setSetup(s=>({...s,backend:e.target.value}))}><option value="isaac">Isaac / Kit</option><option value="light">CPU</option></select></Field>
        <Field label={t('rate')} width={180}><input type="number" min="0.0001" max="100" step="0.01" value={setup.simulation_rate} onChange={e=>setSetup(s=>({...s,simulation_rate:Number(e.target.value)}))}/></Field>
        <button className="primary" disabled={busy}>{busy?t('pending'):t('startNow')}</button><Button onClick={closeForm}>{t('cancel')}</Button>
      </form>:form?<>
        {preview?<div className="preview-line"><div><strong>{t('actualParams')} · {t(preview.kind==='ORDER_CREATE'&&preview.payload.priority==='URGENT'?'urgent':kindNames[preview.kind])}</strong><div className="parameter-summary">{Object.entries(preview.payload).filter(([k])=>!k.includes('sha256')&&k!=='scene_reference').map(([k,v])=><span key={k}>{parameterLabel(k,language)}: {typeof v==='object'?JSON.stringify(v):String(v)}</span>)}</div><small>{t('bindingNote')}</small><small>{preview.target_id} · {preview.time_rule} · #{preview.client_sequence} · {preview.request_id}</small></div><Button className="primary" disabled={busy} onClick={commit}>{t('confirm')}</Button><Button onClick={()=>setPreview(null)}>{t('cancel')}</Button></div>:
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
      </>:<div className="detail-line"><Button onClick={()=>toggleDetails(!details)}>{t('detail')}</Button><span>{picked?`${picked.display_name||picked[language==='zh'?'operation_name_zh':'operation_name_en']||picked.operation_id||picked.resource_id||picked.person_id||''} · ${t(picked.schedule_state?.toLowerCase())}`:t('noSelection')}</span><span className="legend"><i className="solid"/>{t('actual')} <i/>{t(view.full_schedule?'planned':'committed')} {!view.full_schedule&&<><i className="dashed"/>{t('tentative')}</>}</span><Button onClick={()=>rpc('query').then(r=>setView(s=>({...s,...r}))).catch(onError)}>{t('query')}</Button><Button onClick={()=>rpc('evidence').catch(onError)}>{t('evidence')}</Button></div>}
      {error&&<div role="alert" className="error" title={error}>{error}</div>}
    </section>
    {details&&!form&&<div className="details-sheet" style={{left:pad,right:pad,top:auxY,height:auxHeight,maxHeight:auxHeight}}><Button onClick={()=>toggleDetails(false)}>{t('collapse')}</Button>{picked&&<div className="selection-detail"><strong>{picked[language==='zh'?'operation_name_zh':'operation_name_en']||picked.display_name||picked.operation_id}</strong><p>{t('mode')}: {t(picked.schedule_state?.toLowerCase())} · {t(picked.proposal_state?.toLowerCase())||''} · {language==='zh'?'版本':'Version'}: {picked.plan_version||'—'}<br/>{rangeOf(picked)?`${timeLabel(rangeOf(picked)[0],settings.span)} → ${timeLabel(rangeOf(picked)[1],settings.span)} · ${language==='zh'?'区间时长':'Interval'} ${timeLabel(rangeOf(picked)[1]-rangeOf(picked)[0],.01)}`:t('unplanned')} · {(picked.roles||[]).map(x=>x.person_id).join(', ')}<br/>{language==='zh'?'前置工序':'Predecessors'}: {(view.gantt_dependencies||[]).filter(x=>x.target===picked.group_id).map(x=>{const g=(view.gantt_groups||[]).find(g=>g.id===x.source);return g?.[language==='zh'?'name_zh':'name_en']||x.source}).join(' / ')||'—'}</p><small>{t('source')}: {picked.start_event_id||picked.observation_id||'—'} · {picked.operation_id} · {picked.command_id}</small></div>}<table><thead><tr><th>{t('request')}</th><th>{t('effective')}</th><th>{t('business')}</th></tr></thead><tbody>{(view.submitted||[]).map(r=>{const receipt=(view.receipts||[]).find(x=>x.request_id===r.request_id);const business=(view.business_results||[]).filter(x=>x.request_id===r.request_id);return <tr key={r.request_id}><td>{t(r.kind==='ORDER_CREATE'&&r.payload?.priority==='URGENT'?'urgent':kindNames[r.kind])} · {r.target_id}<small>{r.request_id}</small></td><td>{receipt?`${receipt.status} · ${receipt.reason} · ${receipt.actual_applied_sim_h??receipt.sim_h}h`:t('unknownReceipt')}</td><td>{business.length?business.map(x=>x.status||x.kind||x.result).join(' · '):t('unknown')}</td></tr>})}</tbody></table>{!(view.submitted||[]).length&&<p>{t('none')}</p>}</div>}
    <footer style={{left:pad,right:pad,bottom:pad,height:footerHeight}}><span>{view.status==='VERIFIED'?t('fresh'):t(statusNames[view.status]||'unknown')} · {view.writable?t('form'):t('readonly')} · {view.envelope?.observation_id||'—'} · {t('scroll')}</span><div className="range-controls"><label>{t('begin')} <input aria-label={t('begin')} type="number" step="0.1" value={settings.start} onChange={e=>setSettings(s=>({...s,manual:true,follow:false,start:Math.max(0,Number(e.target.value))}))}/></label><label>{t('span')} <input aria-label={t('span')} type="number" min="0.002" step="0.1" value={settings.span} onChange={e=>setSettings(s=>({...s,manual:true,scaleStep:null,span:Math.max(.002,Number(e.target.value))}))}/></label></div></footer>
  </main>
}
createRoot(document.getElementById('root')).render(<App/>);
