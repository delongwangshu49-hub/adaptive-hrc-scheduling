import React,{useEffect,useLayoutEffect,useMemo,useRef,useState} from 'react';
import {useVirtualizer} from '@tanstack/react-virtual';
import {chartRows,rangeOf,fitRange,ticks,timeLabel,scrollDomain,scaleSpan,followStart} from './gantt-model.mjs';
import {overviewLanes} from './experience.mjs';
import {relatesToSelection} from './linkage.mjs';
import {colors} from './theme.mjs';
import {productionRange,productionLane} from './gantt-model.mjs';

export default function Timeline({phase,waitingForPlan,plot:outerPlot,profile,labelWidth,toolbarHeight=36,view,t,selection,selectedIds=[],onSelect,settings,setSettings,onError,rpc,language}){
  const plot={...outerPlot,height:outerPlot.height-16};
  const scrollbar=useRef(null);
  const scrollSync=useRef(false);
  const en=language==='en', parent=useRef(null),canvas=useRef(null),hits=useRef([]),init=useRef(null);
  const [scroll,setScroll]=useState(0),[hover,setHover]=useState(null);
  const [exportNote,setExportNote]=useState(''),[options,setOptions]=useState(false);
  const [productionFocus,setProductionFocus]=useState(0);
  useEffect(()=>{const close=e=>{if(e.key==='Escape'&&options){e.stopPropagation();setOptions(false);}};window.addEventListener('keydown',close,true);return()=>window.removeEventListener('keydown',close,true);},[options]);
  useEffect(()=>{const done=e=>setExportNote((language==='en'?'Saved: ':'已保存：')+e.detail.path);window.addEventListener('hrc-export-complete',done);return()=>window.removeEventListener('hrc-export-complete',done);},[language]);
  const baseItems=useMemo(()=>chartRows(view,{...settings,selectedGroup:selection?.group_id},language),[view.rows,view.gantt_groups,settings,language,selection?.group_id]);
  const items=useMemo(()=>(settings.presentation==='overview'?overviewLanes(baseItems,language):baseItems).map(x=>({...x,height:settings.comfortable===false?x.height:Math.max(36,x.height)})),[baseItems,settings.presentation,settings.comfortable,language]);
  const virtual=useVirtualizer({count:items.length,getScrollElement:()=>parent.current,estimateSize:i=>items[i]?.height||30,overscan:4,paddingEnd:Math.max(0,plot.height-48),getItemKey:i=>items[i]?.id||i});
  const structure=items.map(x=>x.id+":"+x.height).join("|");
  useEffect(()=>{virtual.measure()},[structure]);
  useEffect(()=>{if(!selection)return;const i=items.findIndex(l=>l.rows.some(r=>r.row_id===selection.row_id||r.work_key&&r.work_key===selection.work_key));if(i>=0)virtual.scrollToIndex(i,{align:'auto'});},[selection?.row_id,selection?.work_key]);
  const visible=virtual.getVirtualItems();
  const start=Number.isFinite(settings.start)?settings.start:0,span=settings.span>0?settings.span:1;
  const now=view.envelope?.sampled_sim_h;
  const timed=items.flatMap((lane,index)=>lane.rows.map(row=>({row,index,range:rangeOf(row)}))).filter(x=>x.range);
  const windowHasWork=timed.some(x=>x.range[1]>=start&&x.range[0]<=start+span);
  const edgeWork=windowHasWork?null:timed.reduce((best,x)=>{const distance=x.range[0]>start+span?x.range[0]-start-span:start-x.range[1];return !best||distance<best.distance?{...x,distance}:best;},null);
  useEffect(()=>{if(!productionFocus)return;const i=productionLane(items,now||0);if(i>=0)virtual.scrollToIndex(i,{align:'start'});},[productionFocus]);
  const showProduction=()=>{setSettings(s=>({...s,...productionRange(view.rows||[],now||0),scaleStep:null,follow:phase==='RUNNING',manual:true}));setProductionFocus(n=>n+1);};
  const domain=Math.max(scrollDomain(view.rows||[],span),start+span);
  useEffect(()=>{if(settings.scaleStep)setSettings(s=>({...s,span:scaleSpan(plot.width,s.scaleStep)}));},[plot.width,settings.scaleStep]);
  useLayoutEffect(()=>{scrollSync.current=true;let settled;const frame=requestAnimationFrame(()=>{if(scrollbar.current)scrollbar.current.scrollLeft=start/span*plot.width;settled=requestAnimationFrame(()=>{scrollSync.current=false;});});return ()=>{cancelAnimationFrame(frame);cancelAnimationFrame(settled);};},[start,span,plot.width,domain]);
  const axis=ticks(start,span,plot.width,settings.scaleStep);
  const fit=(selected=false)=>{const rows=selected?items.find(l=>l.rows.some(r=>r.work_key===selection?.work_key))?.rows||[]:items.flatMap(l=>l.rows);setSettings(s=>({...s,...fitRange(rows,now||0),scaleStep:null,follow:false,manual:true}));};
  useEffect(()=>{
    const id=view.envelope?.run_id;
    if(id&&init.current!==id&&(view.rows||[]).some(rangeOf)&&(!view.full_schedule||(view.rows||[]).some(r=>r.row_kind==='FULL_PLAN'))){
      init.current=id;if(!settings.manual){setSettings(s=>({...s,...(phase==='RUNNING'?productionRange(view.rows,now||0):fitRange(view.rows,now||0)),scaleStep:null}));if(phase==='RUNNING')setProductionFocus(n=>n+1);}
    }
    const next=followStart(start,span,now,settings.follow,view.status,phase);
    if(next!==start)setSettings(s=>({...s,start:next}));
  },[view.envelope,view.status,view.rows,settings.follow,start,span,phase]);
  useEffect(()=>{
    const el=canvas.current;if(!el)return;
    const dpr=devicePixelRatio||1;el.width=plot.width*dpr;el.height=plot.height*dpr;
    const c=el.getContext('2d');c.scale(dpr,dpr);c.clearRect(0,0,plot.width,plot.height);c.fillStyle=colors.bg;c.fillRect(0,0,plot.width,plot.height);c.font=(settings.comfortable===false?'12':'14')+'px "Microsoft YaHei UI",sans-serif';
    const x=h=>(h-start)/span*plot.width;hits.current=[];
    for(const tick of axis){c.strokeStyle=colors.raised;c.beginPath();c.moveTo(x(tick.time),0);c.lineTo(x(tick.time),plot.height);c.stroke();}
    const anchors=new Map();
    for(const it of visible){
      const lane=items[it.index],y=it.start-scroll;
      c.strokeStyle=colors.raised;c.beginPath();c.moveTo(0,y+it.size);c.lineTo(plot.width,y+it.size);c.stroke();
      if(lane.heading){c.fillStyle=colors.surface;c.fillRect(0,y,plot.width,it.size-1);continue;}
      let drawn=false;
      for(const r of [...lane.rows].sort((a,b)=>(a.schedule_state==='ACTUAL')-(b.schedule_state==='ACTUAL'))){
        const iv=rangeOf(r);if(!iv||r.schedule_state==='UNSCHEDULED')continue;
        const actual=r.schedule_state==='ACTUAL',old=r.proposal_state==='SUPERSEDED',blocked=r.proposal_state==='RETAINED_BLOCKED';
        const yy=y+(old&&it.size>36?29:10),height=14;
        const related=relatesToSelection(r,selectedIds),primary=selection?.row_id===r.row_id;
        let a=x(iv[0]),b=x(iv[1]);if(b<0||a>plot.width)continue;
        drawn=true;const color=actual?colors.actual:colors.plan;c.strokeStyle=color;c.fillStyle=color;c.lineWidth=1;c.setLineDash(actual||['COMMITTED','PLANNED'].includes(r.schedule_state)?[]:[4,3]);
        if(r.row_kind==='MARKER'){c.beginPath();c.moveTo(a,yy);c.lineTo(a+4,yy+5);c.lineTo(a,yy+10);c.lineTo(a-4,yy+5);c.closePath();c.fill();}
        else if(actual){
          const activeEnd=r.hold_from_h==null?b:Math.min(b,x(r.hold_from_h));c.fillRect(a,yy,Math.max(1,activeEnd-a),height);
          if(activeEnd<b){c.setLineDash([2,3]);c.strokeStyle=colors.muted;c.strokeRect(activeEnd,yy,b-activeEnd,height);}
          if(it.size>30&&Number.isFinite(r.dispatch_earliest_end_h)){
            const end=x(r.dispatch_earliest_end_h);c.strokeStyle=color;c.setLineDash([4,3]);c.strokeRect(a,y+29,Math.max(1,end-a),10);
            hits.current.push({x:a,y:y+29,w:Math.max(5,end-a),h:10,row:{...r,display_note:en?'Frozen earliest finish at dispatch; not guaranteed completion':'启动时冻结的最早结束估计；不保证完成'},iv:[iv[0],r.dispatch_earliest_end_h]});
          }
        }else{c.globalAlpha=old||blocked?.5:1;if(blocked)c.setLineDash([3,4]);c.strokeRect(a,yy,Math.max(1,b-a),height);c.globalAlpha=1;}
        c.setLineDash([]);
        if(related||primary){c.strokeStyle=colors.accent;c.lineWidth=primary?2:1;c.strokeRect(a-2,yy-3,Math.max(1,b-a)+4,height+6);c.lineWidth=1;}
        if(!actual&&r.end_status==='WINDOW_CENSORED'){c.fillText('›',b-8,yy+11);}
        if(actual&&b-a>85){c.fillStyle=colors.onaccent;c.save();c.beginPath();c.rect(a+2,yy,b-a-4,height);c.clip();c.fillText(timeLabel(iv[1]-iv[0],iv[1]-iv[0]),a+5,yy+11);c.restore();}
        hits.current.push({x:a,y:yy,w:Math.max(5,b-a),h:height,row:r,iv});
        if(!anchors.has(lane.id)||!actual)anchors.set(lane.id,{a,b,y:yy+height/2});
      }
      if(!drawn&&!lane.waiting){c.fillStyle=colors.muted;if(!lane.rows.some(rangeOf))c.fillText(en?'Unscheduled · no predicted interval':'待排程 · 尚无预测区间',10,y+20);}
    }
    const group=selection?.group_id;
    if(settings.links!==false)for(const e of view.gantt_dependencies||[]){
      if(!settings.allLinks&&e.source!==group&&e.target!==group)continue;
      const a=anchors.get(e.source),b=anchors.get(e.target);if(!a||!b)continue;
      c.strokeStyle=colors.muted;c.lineWidth=1;c.beginPath();c.moveTo(a.b,a.y);c.lineTo(a.b+7,a.y);c.lineTo(a.b+7,b.y);c.lineTo(b.a,b.y);c.stroke();c.beginPath();c.moveTo(b.a-4,b.y-3);c.lineTo(b.a,b.y);c.lineTo(b.a-4,b.y+3);c.stroke();
    }
    for(const o of view.orders||[]){if(!Number.isFinite(o.due_h))continue;const px=x(o.due_h);if(px<0||px>plot.width)continue;c.strokeStyle=colors.warning;c.setLineDash([2,4]);c.beginPath();c.moveTo(px,0);c.lineTo(px,plot.height);c.stroke();c.setLineDash([]);}
    if(Number.isFinite(now)&&now>=start&&now<=start+span){const px=x(now);c.strokeStyle=colors.ink;c.lineWidth=1;c.beginPath();c.moveTo(px,0);c.lineTo(px,plot.height);c.stroke();c.fillStyle=colors.ink;c.beginPath();c.moveTo(px-4,0);c.lineTo(px+4,0);c.lineTo(px,6);c.closePath();c.fill();}
  },[plot,visible,items,scroll,start,span,selection,selectedIds,view.envelope,view.orders,settings.links,settings.allLinks,language]);
  const at=e=>{const r=e.currentTarget.getBoundingClientRect();return {x:e.clientX-r.left,y:e.clientY-r.top};};
  const hit=e=>{const {x,y}=at(e);return [...hits.current].reverse().find(h=>x>=h.x-3&&x<=h.x+h.w+3&&y>=h.y-3&&y<=h.y+h.h+3);};
  const wheel=e=>{e.preventDefault();if(e.ctrlKey){const ratio=at(e).x/plot.width;const next=Math.max(.002,Math.min(10000,span*(e.deltaY>0?1.2:1/1.2)));setSettings(s=>({...s,manual:true,scaleStep:null,start:Math.max(0,start+ratio*(span-next)),span:next}));}else if(e.shiftKey)setSettings(s=>({...s,manual:true,follow:false,start:Math.max(0,start+e.deltaY/600*span)}));else if(parent.current)parent.current.scrollTop+=e.deltaY;};
  const toggle=id=>setSettings(s=>({...s,expanded:s.expanded?.includes(id)?s.expanded.filter(x=>x!==id):[...(s.expanded||[]),id]}));
  const moveSelection=(event,index)=>{if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();let next=event.key==='Home'?0:event.key==='End'?items.length-1:Math.max(0,Math.min(items.length-1,index+(event.key==='ArrowDown'?1:-1)));const direction=next>=index?1:-1;while(items[next]&&!items[next].rows?.length&&next>=0&&next<items.length)next+=direction;if(items[next]?.rows?.length){onSelect(items[next].rows[0]);virtual.scrollToIndex(next,{align:'auto'});requestAnimationFrame(()=>document.querySelector(`[data-lane-index="${next}"]`)?.focus());}}};
  const exportCurrent=format=>{if(!format)return;setExportNote('');const lanes=(format==='csv'?items:visible.filter(x=>x.end>scroll&&x.start<scroll+plot.height).map(x=>items[x.index])).filter(l=>l.rows?.length).map(l=>({name:l.name,row_ids:l.rows.map(r=>r.row_id)}));const action=format==='json'?'export':'export_view';rpc(action,{format:format.replace('dual_',''),dual:format.startsWith('dual_'),selection,start,span,lanes,filter_summary:`${settings.mode} · product=${settings.product||'all'} · query=${settings.query||'—'} · state=${settings.states?.join(',')||'all'} · ${format==='csv'?'filtered rows':'visible rows'}`}).then(r=>setExportNote(r.status==='CAPTURING_SCENE'?(en?'Capturing scene; simulation remains active…':'正在捕获场景；仿真继续运行……'):r.path?(en?'Saved: ':'已保存：')+r.path:(en?'Export cancelled':'已取消导出'))).catch(onError);};
  return <>
    <div className="timeline-toolbar gantt-tools" style={{left:plot.x-labelWidth,top:plot.y-toolbarHeight,width:plot.width+labelWidth,height:toolbarHeight}}>
      <button title={en?'Show the work around the production clock':'显示当前生产时刻附近的工作'} onClick={showProduction}>{en?'Production now':'当前生产'}</button>
      <button onClick={()=>fit()}>{en?'Full plan':'全程'}</button>
      <button disabled={!selection&&!selectedIds.length} onClick={()=>{const related=(view.rows||[]).filter(r=>relatesToSelection(r,selectedIds)||r.work_key&&r.work_key===selection?.work_key);setSettings(s=>({...s,...fitRange(related,0),scaleStep:null,follow:false,manual:true}));}}>{en?'Selection':'所选对象'}</button>
      <input aria-label={t('filter')} placeholder={en?'Find process':'搜索工序'} value={settings.query} onChange={e=>setSettings(s=>({...s,query:e.target.value}))}/>
      <button aria-expanded={options} onClick={()=>setOptions(!options)}>{en?'View & export':'视图与导出'} ▾</button>
    </div>
    {options&&<>
    <div className="timeline-options" style={{left:plot.x-labelWidth,top:plot.y,width:plot.width+labelWidth}}>
      <div><button onClick={()=>setOptions(false)}>{en?'Close options':'收起选项'}</button><select aria-label={t('mode')} value={settings.mode} onChange={e=>setSettings(s=>({...s,mode:e.target.value}))}><option value="operation">{t('operation')}</option><option value="resource">{t('resource')}</option></select><select aria-label={t('all')} value={settings.product} onChange={e=>setSettings(s=>({...s,product:e.target.value}))}><option value="">{t('all')}</option>{(view.orders||[]).map(o=><option key={o.id} value={o.id}>{o.order_id} / {o.id}</option>)}</select><input aria-label={t('filter')} placeholder={en?'Find process':'搜索工序'} value={settings.query} onChange={e=>setSettings(s=>({...s,query:e.target.value}))}/><select aria-label={t('stateFilter')} value={settings.states?.[0]||''} onChange={e=>setSettings(s=>({...s,states:e.target.value?[e.target.value]:[]}))}><option value="">{t('allStates')}</option>{['ACTUAL','PLANNED','COMMITTED','TENTATIVE','UNSCHEDULED','SUPERSEDED'].map(v=><option key={v} value={v}>{t(v.toLowerCase())}</option>)}</select><select aria-label={en?'Export format':'导出格式'} value="" onChange={e=>exportCurrent(e.target.value)}><option value="">{t('export')}</option><option value="dual_png">PNG · {en?'scene + timeline':'场景 + 甘特'}</option><option value="dual_pdf">PDF · {en?'scene + timeline':'场景 + 甘特'}</option><option value="png">PNG · {en?'current view':'当前视图'}</option><option value="pdf">PDF · {en?'current view':'当前视图'}</option><option value="csv">CSV · {en?'filtered rows':'筛选结果'}</option><option value="json">JSON · {en?'full projection':'完整投影'}</option></select><select aria-label={en?'View level':'浏览层级'} value={settings.presentation||'chart'} onChange={e=>setSettings(s=>({...s,presentation:e.target.value}))}><option value="chart">{en?'Process detail':'工序细节'}</option><option value="overview">{en?'Product overview':'产品概览'}</option><option value="table">{en?'Accessible table':'工序表格'}</option></select></div>
      <div><select aria-label={en?'Hours per grid':'每格小时数'} value={settings.scaleStep||'auto'} onChange={e=>{const step=Number(e.target.value);setSettings(s=>({...s,scaleStep:step,span:scaleSpan(plot.width,step),manual:true}));}}>{!settings.scaleStep&&<option value="auto" disabled>{en?'Auto scale':'自动刻度'}</option>}{[1,2,5,10,20,50,100].map(step=><option key={step} value={step}>{step} h/{en?'grid':'格'}</option>)}</select><button onClick={()=>fit()}>{en?'Full plan':'全程'}</button><button disabled={!Number.isFinite(now)} onClick={()=>setSettings(s=>({...s,start:Math.max(0,now-span*.25),follow:phase==='RUNNING',manual:true}))}>{en?'Current time':'当前时刻'}</button><button disabled={!selection} onClick={()=>fit(true)}>{en?'Selection':'所选工序'}</button><label className="check"><input type="checkbox" checked={!!settings.follow} onChange={e=>setSettings(s=>({...s,follow:e.target.checked}))}/>{en?'Follow':'跟随'}</label><label className="check"><input type="checkbox" checked={!!settings.compare} onChange={e=>setSettings(s=>({...s,compare:e.target.checked}))}/>{en?'Compare':'旧新'}</label><label className="check"><input type="checkbox" checked={!!settings.allLinks} onChange={e=>setSettings(s=>({...s,allLinks:e.target.checked}))}/>{en?'Links':'依赖'}</label><label className="check"><input type="checkbox" checked={!!settings.showUnscheduled} onChange={e=>setSettings(s=>({...s,showUnscheduled:e.target.checked}))}/>{en?'Unscheduled':'待排'}</label><select aria-label={en?'Name width':'名称栏宽'} value={labelWidth} onChange={e=>rpc('labelwidth',{width:Number(e.target.value)}).catch(onError)}>{[...new Set([170,180,210,230,260,300,labelWidth])].sort((a,b)=>a-b).map(n=><option key={n}>{n}</option>)}</select></div>
    </div>
    </>}
    <div className="plot-labels" style={{visibility:settings.presentation==='table'?'hidden':'visible',left:plot.x-labelWidth,top:plot.y,width:labelWidth,height:plot.height}}><div ref={parent} onScroll={e=>setScroll(e.currentTarget.scrollTop)} style={{height:'100%',overflowY:'auto'}}><div style={{height:virtual.getTotalSize(),position:'relative'}}>{visible.map(it=>{const l=items[it.index];return <div key={l.id} className={'gantt-label '+(l.heading?'heading ':'')+(l.detail?'detail ':'')+(l.id===selection?.group_id||l.rows.some(r=>relatesToSelection(r,selectedIds))?'selected':'')} style={{position:'absolute',top:it.start,height:it.size,width:'100%'}}><button className="gantt-name" data-lane-index={it.index} onKeyDown={e=>moveSelection(e,it.index)} title={l.name+'\n'+l.id} onClick={()=>l.rows[0]&&onSelect({...l.rows[0],display_name:l.name})}><strong>{l.name}</strong></button>{!l.heading&&!l.detail&&!l.waiting&&settings.mode==='operation'&&<button className="expand" aria-label={(en?'Expand ':'展开 ')+l.name} onClick={()=>toggle(l.id)}>{settings.expanded?.includes(l.id)?'−':'+'}</button>}</div>})}</div></div></div>
    <canvas ref={canvas} tabIndex={settings.presentation==='table'?-1:0} className="gantt-canvas" aria-hidden={settings.presentation==='table'} aria-label={t('gantt')+' '+t('readonly')} style={{left:plot.x,top:plot.y,width:plot.width,height:plot.height}} onWheel={wheel} onClick={e=>{const h=hit(e);onSelect(h?.row||null)}} onMouseMove={e=>setHover(hit(e)||null)} onMouseLeave={()=>setHover(null)} onKeyDown={e=>{if(['ArrowLeft','ArrowRight'].includes(e.key))setSettings(s=>({...s,manual:true,follow:false,start:Math.max(0,start+(e.key==='ArrowRight'?1:-1)*span/8)}));}}/>
    {edgeWork&&settings.presentation!=='table'&&<button className="timeline-edge" style={{position:'absolute',left:plot.x+8,top:plot.y+32,maxWidth:plot.width-16,zIndex:4,whiteSpace:'normal',fontSize:12}} onClick={()=>{setSettings(s=>({...s,...fitRange([edgeWork.row],0),scaleStep:null,follow:false,manual:true}));virtual.scrollToIndex(edgeWork.index,{align:'start'});}}>{en?'No work in this window · jump to ':'此时间窗无工作 · 跳到 '}{timeLabel(edgeWork.range[0],span)} {edgeWork.range[0]>start?'→':'←'}</button>}
    <div ref={scrollbar} className="time-scrollbar" tabIndex="0" aria-label={en?'Scroll simulation hours':'横向滚动模拟小时'} style={{left:plot.x,top:plot.y+plot.height,width:plot.width,height:16}} onScroll={e=>{if(scrollSync.current)return;const pixels=e.currentTarget.scrollLeft;if(Math.abs(pixels-start/span*plot.width)<=1)return;const next=pixels/plot.width*span;if(Math.abs(next-start)>1e-6)setSettings(s=>({...s,start:next,manual:true,follow:false}));}}><div style={{width:Math.max(plot.width,domain/span*plot.width),height:1}}/></div>
    <div className="time-axis" style={{left:plot.x,top:plot.y+plot.height+16,width:plot.width,height:24}}>{axis.map(a=><span style={{position:'absolute',left:(a.time-start)/span*plot.width,transform:a.time>=start+span*.98?'translateX(-100%)':'translateX(2px)'}} key={a.time}>{a.label}</span>)}</div>
    {hover&&<div className="gantt-hover" style={{left:plot.x+8,top:plot.y+plot.height-65,maxWidth:plot.width-16}}>{hover.row.display_note||hover.row[en?'operation_name_en':'operation_name_zh']||hover.row.operation_id}<br/>{timeLabel(hover.iv[0],span)} → {timeLabel(hover.iv[1],span)} · {t(hover.row.schedule_state?.toLowerCase())}{hover.row.end_status==='WINDOW_CENSORED'?' · '+(en?'window truncated':'窗口截尾'):''}</div>}
    {settings.presentation==='table'&&<div className="accessible-table" style={{left:plot.x-labelWidth,top:plot.y,width:plot.width+labelWidth,height:plot.height}}><table><caption>{en?'Filtered work. Select a row to inspect its actual or planned interval.':'筛选后的工作；选择行可查看实际或计划区间。'}</caption><thead><tr><th>{en?'Work':'工作'}</th><th>{en?'State':'状态'}</th><th>{en?'Start (h)':'起点 (h)'}</th><th>{en?'End (h)':'终点 (h)'}</th><th>{en?'People':'人员'}</th></tr></thead><tbody>{items.flatMap(l=>l.rows.map(r=>({lane:l,row:r}))).slice(0,500).map(({lane,row},i)=>{const iv=rangeOf(row);return <tr key={lane.id+row.row_id+i} aria-selected={selection?.row_id===row.row_id||relatesToSelection(row,selectedIds)}><td><button onClick={()=>onSelect(row)}>{row[en?'operation_name_en':'operation_name_zh']||lane.name}</button></td><td>{t(row.schedule_state?.toLowerCase())}</td><td>{iv?.[0]?.toFixed(4)??'—'}</td><td>{iv?.[1]?.toFixed(4)??'—'}</td><td>{(row.roles||[]).map(x=>x.person_id).join(', ')||'—'}</td></tr>})}</tbody></table>{items.flatMap(x=>x.rows).length>500&&<p>{en?'Showing 500 rows. Narrow the filters or export CSV.':'显示前 500 行，请缩小筛选范围或导出 CSV。'}</p>}</div>}
    <div className="timeline-minimap" style={{left:plot.x,top:plot.y-7,width:plot.width,height:6}} aria-hidden="true"><i style={{left:Math.min(100,start/domain*100)+'%',width:Math.min(100,span/domain*100)+'%'}}/></div>
    {exportNote&&<div className="export-note" role="status">{exportNote}<button onClick={()=>setExportNote('')}>{en?'Close':'关闭'}</button></div>}
    {!!view.full_schedule?.failure&&<div role="status" className="plan-blocked" style={{left:plot.x+6,top:plot.y+22,maxWidth:plot.width-12}}><strong>{en?'Plan blocked · retained schedule is not executable':'排程受阻 · 保留计划暂不可执行'}</strong><details><summary>{en?'Reason and recovery':'原因与恢复'}</summary>{en?'Submit a valid repair/return or cancel affected work. Accepted future recovery waits at safe simulation boundaries.':'请提交合法维修/返回，或取消受影响工作。已接纳的未来恢复按安全模拟边界等待。'}<pre>{view.full_schedule.failure}</pre></details></div>}
    {!!view.forecast_audit_pending&&<span className="forecast-pending" style={{position:"absolute",left:plot.x+8,top:plot.y+18,color:"#C5AD7A",fontSize:12}}>{en?"Forecast verification in progress":"预测区间正在独立核验"}</span>}
    {(waitingForPlan||!items.length)&&<div className="empty" style={{left:plot.x+16,top:plot.y+40}}>{t(waitingForPlan?'waiting':'empty')}</div>}
  </>;
}
