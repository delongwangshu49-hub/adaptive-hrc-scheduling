import React,{useEffect,useLayoutEffect,useMemo,useRef,useState} from 'react';
import {useVirtualizer} from '@tanstack/react-virtual';
import {chartRows,rangeOf,fitRange,ticks,timeLabel,scrollDomain,scaleSpan,followStart} from './gantt-model.mjs';

export default function Timeline({phase,plot:outerPlot,profile,labelWidth,view,t,selection,onSelect,settings,setSettings,onError,rpc,language}){
  const plot={...outerPlot,height:outerPlot.height-16};
  const scrollbar=useRef(null);
  const scrollSync=useRef(false);
  const en=language==='en', parent=useRef(null),canvas=useRef(null),hits=useRef([]),init=useRef(null);
  const [scroll,setScroll]=useState(0),[hover,setHover]=useState(null);
  const items=useMemo(()=>chartRows(view,{...settings,selectedGroup:selection?.group_id},language),[view.rows,view.gantt_groups,settings,language,selection?.group_id]);
  const virtual=useVirtualizer({count:items.length,getScrollElement:()=>parent.current,estimateSize:i=>items[i]?.height||30,overscan:4,getItemKey:i=>items[i]?.id||i});
  const structure=items.map(x=>x.id+":"+x.height).join("|");
  useEffect(()=>{virtual.measure()},[structure]);
  const visible=virtual.getVirtualItems();
  const start=Number.isFinite(settings.start)?settings.start:0,span=settings.span>0?settings.span:1;
  const now=view.envelope?.sampled_sim_h;
  const domain=Math.max(scrollDomain(view.rows||[],span),start+span);
  useEffect(()=>{if(settings.scaleStep)setSettings(s=>({...s,span:scaleSpan(plot.width,s.scaleStep)}));},[plot.width,settings.scaleStep]);
  useLayoutEffect(()=>{scrollSync.current=true;let settled;const frame=requestAnimationFrame(()=>{if(scrollbar.current)scrollbar.current.scrollLeft=start/span*plot.width;settled=requestAnimationFrame(()=>{scrollSync.current=false;});});return ()=>{cancelAnimationFrame(frame);cancelAnimationFrame(settled);};},[start,span,plot.width,domain]);
  const axis=ticks(start,span,plot.width,settings.scaleStep);
  const fit=(selected=false)=>{const rows=selected?items.find(l=>l.rows.some(r=>r.work_key===selection?.work_key))?.rows||[]:items.flatMap(l=>l.rows);setSettings(s=>({...s,...fitRange(rows,now||0),scaleStep:null,follow:false,manual:true}));};
  useEffect(()=>{
    const id=view.envelope?.run_id;
    if(id&&init.current!==id&&(view.rows||[]).some(rangeOf)&&(!view.full_schedule||(view.rows||[]).some(r=>r.row_kind==='FULL_PLAN'))){
      init.current=id;if(!settings.manual)setSettings(s=>({...s,start:0,span:scaleSpan(plot.width,s.scaleStep||10)}));
    }
    const next=followStart(start,span,now,settings.follow,view.status,phase);
    if(next!==start)setSettings(s=>({...s,start:next}));
  },[view.envelope,view.status,view.rows,settings.follow,start,span,phase]);
  useEffect(()=>{
    const el=canvas.current;if(!el)return;
    const dpr=devicePixelRatio||1;el.width=plot.width*dpr;el.height=plot.height*dpr;
    const c=el.getContext('2d');c.scale(dpr,dpr);c.clearRect(0,0,plot.width,plot.height);c.fillStyle='#151515';c.fillRect(0,0,plot.width,plot.height);c.font='12px "Microsoft YaHei UI",sans-serif';
    const x=h=>(h-start)/span*plot.width;hits.current=[];
    for(const tick of axis){c.strokeStyle='#303030';c.beginPath();c.moveTo(x(tick.time),0);c.lineTo(x(tick.time),plot.height);c.stroke();}
    const anchors=new Map();
    for(const it of visible){
      const lane=items[it.index],y=it.start-scroll;
      c.strokeStyle='#333333';c.beginPath();c.moveTo(0,y+it.size);c.lineTo(plot.width,y+it.size);c.stroke();
      if(lane.heading){c.fillStyle='#252525';c.fillRect(0,y,plot.width,it.size-1);continue;}
      let drawn=false;
      for(const r of [...lane.rows].sort((a,b)=>(a.schedule_state==='ACTUAL')-(b.schedule_state==='ACTUAL'))){
        const iv=rangeOf(r);if(!iv||r.schedule_state==='UNSCHEDULED')continue;
        const actual=r.schedule_state==='ACTUAL',old=r.proposal_state==='SUPERSEDED',blocked=r.proposal_state==='RETAINED_BLOCKED';
        const yy=y+(old&&it.size>30?29:8),height=14;
        let a=x(iv[0]),b=x(iv[1]);if(b<0||a>plot.width)continue;
        drawn=true;const color=r.color||'#C5AD7A';c.strokeStyle=color;c.fillStyle=color;c.lineWidth=selection?.row_id===r.row_id?2:1;c.setLineDash(actual||['COMMITTED','PLANNED'].includes(r.schedule_state)?[]:[4,3]);
        if(r.row_kind==='MARKER'){c.beginPath();c.moveTo(a,yy);c.lineTo(a+4,yy+5);c.lineTo(a,yy+10);c.lineTo(a-4,yy+5);c.closePath();c.fill();}
        else if(actual){
          const activeEnd=r.hold_from_h==null?b:Math.min(b,x(r.hold_from_h));c.fillRect(a,yy,Math.max(1,activeEnd-a),height);
          if(activeEnd<b){c.setLineDash([2,3]);c.strokeStyle='#aaa';c.strokeRect(activeEnd,yy,b-activeEnd,height);}
          if(it.size>30&&Number.isFinite(r.dispatch_earliest_end_h)){
            const end=x(r.dispatch_earliest_end_h);c.strokeStyle=color;c.setLineDash([4,3]);c.strokeRect(a,y+29,Math.max(1,end-a),10);
            hits.current.push({x:a,y:y+29,w:Math.max(5,end-a),h:10,row:{...r,display_note:en?'Frozen earliest finish at dispatch; not guaranteed completion':'启动时冻结的最早结束估计；不保证完成'},iv:[iv[0],r.dispatch_earliest_end_h]});
          }
        }else{c.globalAlpha=old||blocked?.5:1;if(blocked)c.setLineDash([3,4]);c.strokeRect(a,yy,Math.max(1,b-a),height);c.globalAlpha=1;}
        c.setLineDash([]);
        if(!actual&&r.end_status==='WINDOW_CENSORED'){c.fillText('›',b-8,yy+11);}
        if(actual&&b-a>85){c.fillStyle='#171717';c.save();c.beginPath();c.rect(a+2,yy,b-a-4,height);c.clip();c.fillText(timeLabel(iv[1]-iv[0],iv[1]-iv[0]),a+5,yy+11);c.restore();}
        hits.current.push({x:a,y:yy,w:Math.max(5,b-a),h:height,row:r,iv});
        if(!anchors.has(lane.id)||!actual)anchors.set(lane.id,{a,b,y:yy+height/2});
      }
      if(!drawn&&!lane.waiting){c.fillStyle='#99958F';c.fillText(lane.rows.some(rangeOf)?(en?'Outside this time window':'当前时间范围之外'):(en?'Unscheduled · no predicted interval':'待排程 · 尚无预测区间'),10,y+20);}
    }
    const group=selection?.group_id;
    if(settings.links!==false)for(const e of view.gantt_dependencies||[]){
      if(!settings.allLinks&&e.source!==group&&e.target!==group)continue;
      const a=anchors.get(e.source),b=anchors.get(e.target);if(!a||!b)continue;
      c.strokeStyle='#B3B0AB';c.lineWidth=1;c.beginPath();c.moveTo(a.b,a.y);c.lineTo(a.b+7,a.y);c.lineTo(a.b+7,b.y);c.lineTo(b.a,b.y);c.stroke();c.beginPath();c.moveTo(b.a-4,b.y-3);c.lineTo(b.a,b.y);c.lineTo(b.a-4,b.y+3);c.stroke();
    }
    for(const o of view.orders||[]){if(!Number.isFinite(o.due_h))continue;const px=x(o.due_h);if(px<0||px>plot.width)continue;c.strokeStyle='#C5AD7A';c.setLineDash([2,4]);c.beginPath();c.moveTo(px,0);c.lineTo(px,plot.height);c.stroke();c.setLineDash([]);}
    if(Number.isFinite(now)&&now>=start&&now<=start+span){const px=x(now);c.strokeStyle='#E7E5E1';c.lineWidth=1;c.beginPath();c.moveTo(px,0);c.lineTo(px,plot.height);c.stroke();c.fillStyle='#E7E5E1';c.fillText((en?'Sim time ':'模拟时间 ')+timeLabel(now,span),Math.max(3,Math.min(plot.width-105,px+5)),13);}
  },[plot,visible,items,scroll,start,span,selection,view.envelope,view.orders,settings.links,settings.allLinks,language]);
  const at=e=>{const r=e.currentTarget.getBoundingClientRect();return {x:e.clientX-r.left,y:e.clientY-r.top};};
  const hit=e=>{const {x,y}=at(e);return [...hits.current].reverse().find(h=>x>=h.x-3&&x<=h.x+h.w+3&&y>=h.y-3&&y<=h.y+h.h+3);};
  const wheel=e=>{e.preventDefault();if(e.ctrlKey){const ratio=at(e).x/plot.width;const next=Math.max(.002,Math.min(10000,span*(e.deltaY>0?1.2:1/1.2)));setSettings(s=>({...s,manual:true,scaleStep:null,start:Math.max(0,start+ratio*(span-next)),span:next}));}else if(e.shiftKey)setSettings(s=>({...s,manual:true,follow:false,start:Math.max(0,start+e.deltaY/600*span)}));else if(parent.current)parent.current.scrollTop+=e.deltaY;};
  const toggle=id=>setSettings(s=>({...s,expanded:s.expanded?.includes(id)?s.expanded.filter(x=>x!==id):[...(s.expanded||[]),id]}));
  return <>
    <div className="timeline-toolbar gantt-tools" style={{left:plot.x-labelWidth,top:plot.y-64,width:plot.width+labelWidth,height:64}}>
      <div><select aria-label={t('mode')} value={settings.mode} onChange={e=>setSettings(s=>({...s,mode:e.target.value}))}><option value="operation">{t('operation')}</option><option value="resource">{t('resource')}</option></select><select aria-label={t('all')} value={settings.product} onChange={e=>setSettings(s=>({...s,product:e.target.value}))}><option value="">{t('all')}</option>{(view.orders||[]).map(o=><option key={o.id} value={o.id}>{o.order_id} / {o.id}</option>)}</select><input aria-label={t('filter')} placeholder={en?'Find process':'搜索工序'} value={settings.query} onChange={e=>setSettings(s=>({...s,query:e.target.value}))}/><select aria-label={t('stateFilter')} value={settings.states?.[0]||''} onChange={e=>setSettings(s=>({...s,states:e.target.value?[e.target.value]:[]}))}><option value="">{t('allStates')}</option>{['ACTUAL','PLANNED','COMMITTED','TENTATIVE','UNSCHEDULED','SUPERSEDED'].map(v=><option key={v} value={v}>{t(v.toLowerCase())}</option>)}</select><button onClick={()=>rpc('export',{selection}).catch(onError)}>{t('export')}</button></div>
      <div><select aria-label={en?'Hours per grid':'每格小时数'} value={settings.scaleStep||'auto'} onChange={e=>{const step=Number(e.target.value);setSettings(s=>({...s,scaleStep:step,span:scaleSpan(plot.width,step),manual:true}));}}>{!settings.scaleStep&&<option value="auto" disabled>{en?'Auto scale':'自动刻度'}</option>}{[1,2,5,10,20,50,100].map(step=><option key={step} value={step}>{step} h/{en?'grid':'格'}</option>)}</select><button onClick={()=>fit()}>{en?'Full plan':'全程'}</button><button disabled={!selection} onClick={()=>fit(true)}>{en?'Selection':'所选工序'}</button><label className="check"><input type="checkbox" checked={!!settings.follow} onChange={e=>setSettings(s=>({...s,follow:e.target.checked}))}/>{en?'Follow':'跟随'}</label><label className="check"><input type="checkbox" checked={!!settings.compare} onChange={e=>setSettings(s=>({...s,compare:e.target.checked}))}/>{en?'Compare':'旧新'}</label><label className="check"><input type="checkbox" checked={!!settings.allLinks} onChange={e=>setSettings(s=>({...s,allLinks:e.target.checked}))}/>{en?'Links':'依赖'}</label><label className="check"><input type="checkbox" checked={!!settings.showUnscheduled} onChange={e=>setSettings(s=>({...s,showUnscheduled:e.target.checked}))}/>{en?'Unscheduled':'待排'}</label><select aria-label={en?'Name width':'名称栏宽'} value={labelWidth} onChange={e=>rpc('labelwidth',{width:Number(e.target.value)}).catch(onError)}>{[170,210,260,300].map(n=><option key={n}>{n}</option>)}</select></div>
    </div>
    <div className="plot-labels" style={{left:plot.x-labelWidth,top:plot.y,width:labelWidth,height:plot.height}}><div ref={parent} onScroll={e=>setScroll(e.currentTarget.scrollTop)} style={{height:'100%',overflowY:'auto'}}><div style={{height:virtual.getTotalSize(),position:'relative'}}>{visible.map(it=>{const l=items[it.index];return <div key={l.id} className={'gantt-label '+(l.heading?'heading ':'')+(l.detail?'detail ':'')+(l.id===selection?.group_id?'selected':'')} style={{position:'absolute',top:it.start,height:it.size,width:'100%'}}><button className="gantt-name" title={l.name+'\n'+l.id} onClick={()=>l.rows[0]&&onSelect({...l.rows[0],display_name:l.name})}><strong>{l.name}</strong></button>{!l.heading&&!l.detail&&!l.waiting&&settings.mode==='operation'&&<button className="expand" aria-label={(en?'Expand ':'展开 ')+l.name} onClick={()=>toggle(l.id)}>{settings.expanded?.includes(l.id)?'−':'+'}</button>}</div>})}</div></div></div>
    <canvas ref={canvas} tabIndex="0" className="gantt-canvas" aria-label={t('gantt')+' '+t('readonly')} style={{left:plot.x,top:plot.y,width:plot.width,height:plot.height}} onWheel={wheel} onClick={e=>{const h=hit(e);if(h)onSelect(h.row)}} onMouseMove={e=>setHover(hit(e)||null)} onMouseLeave={()=>setHover(null)} onKeyDown={e=>{if(['ArrowLeft','ArrowRight'].includes(e.key))setSettings(s=>({...s,manual:true,follow:false,start:Math.max(0,start+(e.key==='ArrowRight'?1:-1)*span/8)}));}}/>
    <div ref={scrollbar} className="time-scrollbar" tabIndex="0" aria-label={en?'Scroll simulation hours':'横向滚动模拟小时'} style={{left:plot.x,top:plot.y+plot.height,width:plot.width,height:16}} onScroll={e=>{if(scrollSync.current)return;const pixels=e.currentTarget.scrollLeft;if(Math.abs(pixels-start/span*plot.width)<=1)return;const next=pixels/plot.width*span;if(Math.abs(next-start)>1e-6)setSettings(s=>({...s,start:next,manual:true,follow:false}));}}><div style={{width:Math.max(plot.width,domain/span*plot.width),height:1}}/></div>
    <div className="time-axis" style={{left:plot.x,top:plot.y+plot.height+16,width:plot.width,height:24}}>{axis.map(a=><span style={{position:'absolute',left:(a.time-start)/span*plot.width,transform:a.time>=start+span*.98?'translateX(-100%)':'translateX(2px)'}} key={a.time}>{a.label}</span>)}</div>
    {hover&&<div className="gantt-hover" style={{left:plot.x+8,top:plot.y+plot.height-65,maxWidth:plot.width-16}}>{hover.row.display_note||hover.row[en?'operation_name_en':'operation_name_zh']||hover.row.operation_id}<br/>{timeLabel(hover.iv[0],span)} → {timeLabel(hover.iv[1],span)} · {t(hover.row.schedule_state?.toLowerCase())}{hover.row.end_status==='WINDOW_CENSORED'?' · '+(en?'window truncated':'窗口截尾'):''}</div>}
    {!!view.full_schedule?.failure&&<div role="status" className="plan-blocked" style={{left:plot.x+6,top:plot.y+22,maxWidth:plot.width-12}}><strong>{en?'Plan blocked · retained schedule is not executable':'排程受阻 · 保留计划暂不可执行'}</strong><details><summary>{en?'Reason and recovery':'原因与恢复'}</summary>{en?'Submit a valid repair/return or cancel affected work. Accepted future recovery waits at safe simulation boundaries.':'请提交合法维修/返回，或取消受影响工作。已接纳的未来恢复按安全模拟边界等待。'}<pre>{view.full_schedule.failure}</pre></details></div>}
    {!!view.forecast_audit_pending&&<span className="forecast-pending" style={{position:"absolute",left:plot.x+8,top:plot.y+18,color:"#C5AD7A",fontSize:12}}>{en?"Forecast verification in progress":"预测区间正在独立核验"}</span>}
    {!items.length&&<div className="empty" style={{left:plot.x+16,top:plot.y+40}}>{t('empty')}</div>}
  </>;
}
