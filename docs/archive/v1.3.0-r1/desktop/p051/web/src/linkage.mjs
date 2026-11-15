export const cameraLabels={Overview:['全景','Overview'],Top:['俯视','Top'],Supply:['供料区','Supply'],Equipment:['设备区','Equipment'],Crossing:['交汇区','Crossing'],Finished:['成品区','Finished'],Gantry:['龙门区','Gantry'],F1:['一层作业区','Floor 1'],Fork:['叉车区','Forklift'],Test:['检验区','Inspection']};
export function rowEntities(row){
  if(!row)return [];
  return [...new Set([row.person_id,row.resource_id,row.target_id,row.operation_id,row.product_id,row.display_product_id,row.order_id,row.display_order_id,...(row.roles||[]).map(x=>x.person_id),...(row.equipment||[])].filter(Boolean))];
}
export function selectedEntity(row,entities){
  const ids=rowEntities(row),available=new Map((entities||[]).map(x=>[x.id,x]));
  return ids.find(id=>available.get(id)?.paths?.length&&available.get(id)?.visible!==false)||ids[0]||null;
}
export function rowForEntity(rows,ids,previous){
  const matches=(rows||[]).filter(r=>rowEntities(r).some(x=>ids.includes(x)));
  return matches.find(r=>r.row_id===previous?.row_id)||matches.find(r=>r.schedule_state==='ACTUAL'&&r.end_status==='OPEN')||matches.find(r=>r.schedule_state==='ACTUAL')||matches[0]||null;
}
export function restoreSelection(rows,selection){
  if(!selection)return null;
  return rows.find(r=>r.row_id===selection.row_id)||rows.find(r=>r.work_key&&r.work_key===selection.work_key&&r.schedule_state===selection.schedule_state)||{...selection,historical_selection:true};
}
export function synchronization(view,native,phase){
  const scene=native.frame,obs=view.envelope;
  if(phase==='SAVED_READ_ONLY')return 'ARCHIVE';
  if(view.backend==='CPU')return 'CPU';
  if(!scene)return 'CONNECTING';
  if(!scene.fresh)return 'SCENE_STALE';
  if(!obs||native.observation_stale)return 'DATA_STALE';
  return scene.source_state_revision===obs.state_revision?'ALIGNED':'UPDATING';
}
export function relatedTargets(view,request){
  const facts=(view.business_results||[]).filter(r=>r.request_id===request.request_id);
  const products=(view.orders||[]).filter(p=>p.order_id===request.target_id||p.id===request.target_id).map(p=>p.id);
  return [...new Set([...products,...facts.flatMap(f=>f.product_ids||[]),request.target_id].filter(Boolean))];
}
export function requestSteps(view,request,scene){
  const receipt=(view.receipts||[]).find(r=>r.request_id===request.request_id);
  const facts=(view.business_results||[]).filter(r=>r.request_id===request.request_id);
  const status=receipt?.status||'SUBMITTED',targets=relatedTargets(view,request);
  const entities=(scene?.entities||[]).filter(e=>targets.includes(e.id));
  const actualRows=(view.rows||[]).filter(r=>r.schedule_state==='ACTUAL'&&r.row_kind!=='MARKER'&&rowEntities(r).some(id=>targets.includes(id))).length;
  return {status,facts,targets,actualRows,sceneMapped:entities.some(e=>e.paths?.length),sceneVisible:entities.some(e=>e.paths?.length&&e.visible!==false),before:view.request_context?.[request.request_id]?.plan_version_before??null,after:view.verified_full_schedule?.version??null};
}
export function viewCamera(command,previous){
  if(!command?.accepted)return previous;
  return command.action==='camera'?command.camera:['focus','camera_back'].includes(command.action)?'custom':previous;
}
export function startupLabel(phase,en=false){
  const words={STARTING_KIT:['启动 Isaac 引擎','Starting Isaac'],BUILDING_SCENE:['加载生产场景','Building production scene'],FIRST_FRAME_READY:['场景首帧已生成 · 等待业务投影','First scene frame ready · waiting for business projection'],PREPARING_CPU:['准备 CPU 数据会话','Preparing CPU session'],CPU_READY:['CPU 数据会话已就绪','CPU data session ready']};
  return words[phase]?.[en?1:0]||'';
}
