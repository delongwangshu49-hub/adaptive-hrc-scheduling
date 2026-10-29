import {lanesFor} from './model.mjs';

export function rangeOf(r){
  const a=r.start_h??r.sim_h;
  const b=r.end_h??r.observed_until_h??r.forecast_until_h;
  if(r.row_kind==='MARKER'&&Number.isFinite(a))return [a,a];
  return Number.isFinite(a)&&Number.isFinite(b)?[a,b]:null;
}
export function fitRange(rows,now=0,minimum=.02){
  const ranges=rows.map(rangeOf).filter(Boolean);
  if(!ranges.length)return {start:0,span:Math.max(.1,now*1.15)};
  const a=Math.min(...ranges.map(x=>x[0])),b=Math.max(now,...ranges.map(x=>x[1]));
  const span=Math.max(minimum,b-a);
  return {start:Math.max(0,a-span*.05),span:span*1.15};
}
export function navigationSettings(saved={}){
  const defaults={mode:'operation',product:'',query:'',states:[],compare:false,collapsed:[],expanded:[]};
  return saved.navigationVersion===3?{...defaults,...saved}:{...defaults,...saved,navigationVersion:3,start:0,span:40,scaleStep:10,follow:true,manual:false};
}
export function scaleSpan(width,step=10){return Math.max(2,Math.floor(width/85))*step;}
export function followStart(start,span,now,enabled,status,phase){
  if(!enabled||status!=='VERIFIED'||phase!=='RUNNING'||!Number.isFinite(now))return start;
  return now<start||now>start+span*.75?Math.max(0,now-span*.75):start;
}
export function ticks(start,span,width,fixedStep=null){
  const desired=Math.max(2,Math.floor(width/85));const rough=span/desired;
  const power=10**Math.floor(Math.log10(rough));const unit=fixedStep||[1,2,5,10].find(x=>x*power>=rough)*power;
  const result=[];for(let t=Math.ceil(start/unit)*unit;t<=start+span+unit/100;t+=unit)result.push({time:t,label:timeLabel(t,span)});
  return result;
}
export function timeLabel(h,span=1){
  return `${+h.toPrecision(6)} h`;
}
export function chartRows(view,settings,language){
  const en=language==='en',q=(settings.query||'').toLowerCase();
  const visible=(view.rows||[]).filter(r=>{
    if(settings.product&&(r.product_id||r.display_product_id)!==settings.product)return false;
    if((!settings.compare||r.group_id!==settings.selectedGroup)&&r.proposal_state==='SUPERSEDED'&&!settings.states?.includes('SUPERSEDED'))return false;
    if(settings.states?.length&&!settings.states.includes(r.schedule_state)&&!settings.states.includes(r.proposal_state))return false;
    return true;
  });
  if(settings.mode==='resource')return lanesFor(visible,{...settings,query:''}).filter(l=>!q||JSON.stringify(l).toLowerCase().includes(q)).map(l=>({...l,name:l.id,secondary:en?'Resource occupancy':'人员 / 设备占用',height:30}));
  const groups=view.gantt_groups||[];const result=[];let product=null,waiting=0;
  const flush=()=>{if(waiting){result.push({id:'waiting:'+product,name:en?`${waiting} unscheduled processes`:`${waiting} 项工序待排程`,secondary:en?'Show with “Unscheduled” above':'勾选“待排”可查看完整工序',height:30,rows:[],waiting:true});waiting=0;}};
  for(const g of groups){
    if(settings.product&&g.product_id!==settings.product)continue;
    const all=visible.filter(r=>r.group_id===g.id&&!['PERSON_INTERVAL','RESOURCE_FACT'].includes(r.row_kind));
    const name=en?g.name_en:g.name_zh;
    if(q&&!JSON.stringify([g,all]).toLowerCase().includes(q))continue;
    if(settings.states?.length&&!all.length)continue;
    if(product!==g.product_id){flush();product=g.product_id;result.push({id:'product:'+product,name:g.order_id+' / '+product,secondary:en?'Order / Product':'订单 / 产品',heading:true,height:28,rows:[]});}
    const shown=all.filter(r=>r.row_kind!=='PLAN'||r.schedule_state==='UNSCHEDULED');
    const timed=shown.filter(r=>rangeOf(r));
    if(!settings.showUnscheduled&&!q&&!settings.states?.length&&!timed.length){waiting++;continue;}
    const first=timed.find(r=>r.row_kind==='FACT_PREFIX')||timed[0]||shown[0];
    const rows=first?[first,...shown.filter(r=>r!==first)]:shown;
    result.push({...g,name,secondary:timed.length?(en?`${timed.length} segments`:`${timed.length} 个执行 / 计划段`):(en?'Awaiting schedule':'待排程'),rows,height:settings.compare&&settings.selectedGroup===g.id?46:30});
    if(settings.expanded?.includes(g.id)){
      const ops=new Map();for(const r of all){const id=r.operation_id||r.row_id;if(!ops.has(id))ops.set(id,[]);ops.get(id).push(r);}
      for(const [id,rows] of ops)result.push({id,parent:g.id,name:rows[0][en?'operation_name_en':'operation_name_zh']||id,secondary:id,rows,detail:true,height:30});
    }
  }
  flush();
  if(!q&&!settings.product){const markers=visible.filter(r=>r.row_kind==='MARKER');if(markers.length)result.push({id:'events',name:en?'Production events':'生产事件',secondary:en?'Point events, not tasks':'点事件，不代表工期',rows:markers,height:48});}
  return result;
}

export function scrollDomain(rows,span){const ends=rows.map(rangeOf).filter(Boolean).map(x=>x[1]);return Math.max(span,Math.max(...ends,0)*1.02);}
