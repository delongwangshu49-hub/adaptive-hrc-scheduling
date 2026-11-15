import React,{useState} from 'react';
import {rowEntities,selectedEntity,requestSteps,synchronization,startupLabel,cameraLabels} from './linkage.mjs';
import {receiptLabel} from './experience.mjs';

export function SceneTools({view,native,picked,language,rpc,onError,camera,setCamera,style}){
  const en=language==='en',entities=native.scene?.entities||[],ids=rowEntities(picked),fallback=selectedEntity(picked,entities);
  const [explicit,setExplicit]=useState(null),target=ids.includes(explicit)?explicit:fallback;
  const mapped=entities.some(e=>e.id===target&&e.paths?.length&&e.visible!==false),ready=!!native.native_available;
  const send=(action,data={})=>rpc(action,data).catch(onError);
  return <div className="native-tools linked-native-tools" style={style}>
    <select aria-label={en?'Camera preset':'相机视角'} disabled={!ready} value={camera} onChange={e=>{setCamera(e.target.value);send('camera',{camera:e.target.value});}}>{camera==='custom'&&<option value='custom' disabled>{en?'Custom view':'当前自定义视角'}</option>}{Object.entries(cameraLabels).map(([id,label])=><option key={id} value={id}>{label[en?1:0]}</option>)}</select>
    <button disabled={!ready} onClick={()=>send('camera_back')}>{en?'Previous view':'上一视角'}</button>
    <select aria-label={en?'Related scene object':'关联场景对象'} value={target||''} onChange={e=>setExplicit(e.target.value)} disabled={!ids.length}><option value="">{en?'Select work first':'先选择工作'}</option>{ids.map(id=><option key={id}>{id}</option>)}</select>
    <button disabled={!ready||!mapped} title={!mapped?(en?'This object is not mapped into the scene yet':'该对象尚未进入场景'):undefined} onClick={()=>send('focus',{entity_id:target})}>{en?'Focus object':'聚焦对象'}</button>
    <span>{en?'Scene':'场景'} {native.frame?.sampled_sim_h?.toFixed(3)??'—'} h · {native.frame?.fresh?(en?'Updating':'已更新'):(en?'Awaiting frame':'等待画面')}</span>
  </div>;
}

export function ContextStrip({view,native,phase,language,onEvents,style}){
  const en=language==='en',state=synchronization(view,native,phase);
  const labels={ENDED:['Isaac 已退出 · 已保存数据只读','Isaac exited · saved data is read-only'],ARCHIVE:['历史数据 · 不代表三维回放','Archive data · not a 3D replay'],CPU:['CPU 数据模式 · 未启动 Isaac','CPU data mode · Isaac not started'],CONNECTING:['等待 Isaac 场景连接','Waiting for Isaac scene'],SCENE_STALE:['场景画面待更新','Scene frame is stale'],DATA_STALE:['业务数据待更新','Business data is stale'],ALIGNED:['场景与业务状态版本一致','Scene and business revisions aligned'],UPDATING:['两侧正在更新 · 来源时刻分列','Views updating · source times shown separately']};
  const command=native.scene?.last_command;
  return <div className="linked-context" style={style}><span>{labels[state]?.[en?1:0]}</span><span>{en?'Scene':'场景'} r{native.frame?.source_state_revision??'—'} · {en?'Data':'业务'} r{view.envelope?.state_revision??'—'} · {en?'Plan':'计划'} v{view.verified_full_schedule?.version??'—'}</span><button onClick={onEvents}>{en?'Changes & receipts':'变更与回执'}</button>{command&&<span role="status" className={command.accepted?'':'warning-text'}>{en?'View operation':'视图操作'} #{command.sequence} · {command.accepted?(en?'Confirmed':'已确认'):command.reason}</span>}</div>;
}

export function Events({view,native,language,onTarget,onClose,style}){
  const en=language==='en';
  return <section className="inspector event-inspector" style={style}><div className="inspector-tabs"><strong>{en?'Work-order changes → plan → execution / scene':'工单变化 → 计划 → 实际执行 / 场景'}</strong><button onClick={onClose}>{en?'Collapse':'折叠'}</button></div><div className="inspector-body"><p>{en?'Plan changes and scene mapping are separate evidence. A new plan does not mean the work has executed.':'计划更新、实际执行和场景映射分别记录；新计划出现不等于工作已执行。'}</p><table><thead><tr>{(en?['Request / object','Receipt','Verified plan','Business facts / actual rows','Scene']:['请求 / 对象','处理阶段','核验计划','业务事实 / 实际行','场景']).map(x=><th key={x}>{x}</th>)}</tr></thead><tbody>{[...(view.submitted||[])].reverse().map(r=>{const s=requestSteps(view,r,native.scene);return <tr key={r.request_id}><td><button onClick={()=>onTarget(s.targets)}>{r.kind} · {r.target_id}</button><small>{r.request_id}</small></td><td>{receiptLabel(s.status,language)}</td><td>{s.before==null?'—':'v'+s.before} → {s.after==null?'—':'v'+s.after}<small>{en?'before request / current; attribution not inferred':'提交前 / 当前；不推断变化归因'}</small></td><td>{s.facts.length?s.facts.map(x=>receiptLabel(x.status||x.kind||x.result,language)).join(' · '):(en?'No related business fact delivered':'尚未交付关联业务事实')}<small>{en?'Related actual rows: ':'关联实际行：'}{s.actualRows} · {en?'no causal attribution':'不推断请求归因'}</small></td><td>{s.sceneMapped?(s.sceneVisible?(en?'Object visible in scene':'对象已进入场景'):(en?'Registered; not yet visible':'已登记；尚未进入可见场景')):(en?'No direct mapping; inspect related products/resources':'无直接映射，可查看关联产品/资源')}</td></tr>})}</tbody></table>{!view.submitted?.length&&<p>{en?'No requests in this client. Submit an order or resource change after reviewing its parameters.':'本客户端暂无请求。核对参数后提交工单或资源变更，可在此跟踪。'}</p>}</div></section>;
}

export function SceneEmpty({phase,backend,native,language,onSettings,onStart,style}){
  const en=language==='en',historical=phase==='SAVED_READ_ONLY'||phase==='EXITED';
  const startup=historical?'':startupLabel(native.scene?.startup?.phase,en);
  return <div className="native-empty linked-scene-empty" style={style}><strong>{historical?(phase==='EXITED'?(en?'Isaac has exited · session saved':'Isaac 已退出 · 会话已保存'):(en?'Historical data view':'历史数据查看')):backend==='CPU'?(en?'CPU data session':'CPU 数据会话'):(startup||(en?'Isaac production scene':'Isaac 生产仿真场景'))}</strong><p>{historical?(en?'This archive does not provide a synchronized 3D replay. Existing data remains read-only.':'当前存档未提供同步三维回放，已有数据保持只读。'):backend==='CPU'?(en?'This session does not run Isaac. Start a new full simulation to observe scene and schedule together.':'本会话未启动 Isaac。新建完整仿真后可同时观察场景与甘特。'):(en?'Work orders, people and equipment drive the scene. Configuration checks do not yet prove the renderer is running.':'工单、人员和设备变化将驱动场景响应。环境检查通过不代表渲染器已经运行。')}</p>{!startup&&<><button onClick={onStart} disabled={!onStart}>{en?'Full simulation setup':'完整仿真配置'}</button><button onClick={onSettings}>{en?'Check Isaac environment':'检查 Isaac 环境'}</button></>}</div>;
}
