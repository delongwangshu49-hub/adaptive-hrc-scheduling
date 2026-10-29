// View operations consume delivered rows only. No scheduling or business writes.
export const earth=['#C08E77','#C5AD7A','#99A67F','#A59689'];
export function interval(row){
  const start=row.start_h??row.sim_h;
  const end=row.end_h??row.observed_until_h??start;
  return Number.isFinite(start)&&Number.isFinite(end)?[start,end]:null;
}
export function lanesFor(rows,{mode='operation',product='',query='',states=[],compare=false,collapsed=[]}={}){
  const lanes=new Map();
  for(const row of rows){
    if(mode==='operation'&&['PERSON_INTERVAL','RESOURCE_FACT'].includes(row.row_kind))continue;
    if(product&&(row.product_id||row.display_product_id)!==product)continue;
    if(states.length&&!states.includes(row.schedule_state)&&!states.includes(row.proposal_state))continue;
    if(!compare&&!states.includes('SUPERSEDED')&&row.proposal_state==='SUPERSEDED')continue;
    if(query&&!JSON.stringify([row.product_id,row.operation_id,row.resource_id,row.person_id,row.work_number]).toLowerCase().includes(query.toLowerCase()))continue;
    let names=mode==='resource'?[row.resource_id,row.person_id,...(row.row_kind==='MARKER'?[row.target_id]:[]),...(row.equipment||[]),...(row.roles||[]).map(r=>r.person_id)].filter(Boolean):[row.operation_id||row.canonical_lane||row.row_id];
    if(!names.length)continue;
    for(const name of new Set(names)){
      if(!lanes.has(name))lanes.set(name,{id:name,product:row.product_id,rows:[]});
      lanes.get(name).rows.push(row);
    }
  }
  return [...lanes.values()].sort((a,b)=>a.id.localeCompare(b.id)).map(l=>({...l,collapsed:collapsed.includes(l.id)}));
}
export function makePayload(kind,draft){
  const number=(key)=>{const n=Number(draft[key]);if(!Number.isFinite(n))throw Error('INVALID_NUMBER:'+key);return n;};
  if(kind==='ORDER_CREATE')return {template_id:draft.template_id,quantity:number('quantity'),due_sim_h:number('due_sim_h'),priority:draft.priority,material_plan_id:draft.material_plan_id||'TEMPLATE-JIT-v1'};
  if(kind==='ORDER_UPDATE')return {due_sim_h:number('due_sim_h'),priority:draft.priority};
  if(kind==='PERSON_ARRIVE')return {template_id:draft.person_template,arrival_location:draft.arrival_location,initial_f:number('initial_f')};
  if(kind==='PERSON_RETURN')return {arrival_location:draft.arrival_location,scene_entity_id:draft.target_id};
  if(kind==='PERSON_DEPART')return {reason:draft.reason,handover_policy:'SAFE_POINT_OR_VERIFIED_HANDOVER'};
  if(kind==='PERSON_ABSENT')return {reason:draft.reason,safety_policy:'HOLD_AND_VERIFY'};
  if(kind==='REST_REQUEST')return {duration_h:number('duration_h')};
  if(kind==='DEVICE_FAIL'||kind==='ORDER_CANCEL')return {reason:draft.reason};
  if(kind==='DEVICE_REPAIR')return {repair_evidence_id:draft.repair_evidence_id};
  return {};
}

export function laneLabel(id){return id.replace(/^PRODUCT-(\d+)\./,'$1·').replace(/^SERVICE-(\d+)-/,'S$1·');}
