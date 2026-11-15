export const appVersion='1.4.0';
export function requestKindLabel(kind,language='zh'){
  const names={ORDER_CREATE:['新建工单','New order'],ORDER_UPDATE:['修改工单','Update order'],ORDER_CANCEL:['取消工单','Cancel order'],PERSON_ARRIVE:['人员到岗','Person arrival'],PERSON_DEPART:['计划离岗','Planned departure'],PERSON_ABSENT:['人员缺勤','Person absence'],PERSON_RETURN:['人员返回','Person return'],DEVICE_FAIL:['设备故障','Device fault'],DEVICE_REPAIR:['设备维修','Device repair'],CLOSE_INPUT:['关闭接单','Close intake'],STOP_REQUEST:['安全停止','Safe stop']};
  return names[kind]?.[language==='en'?1:0]||kind;
}
export function phaseLabel(phase,language='zh'){
  const names={RUNNING:['运行中','Running'],CONNECTING:['连接中','Connecting'],PREPARING:['准备中','Preparing'],STOPPING:['停止处理中','Stopping'],STOPPED:['生产已停止 · 等待退出','Production stopped · awaiting exit'],EXITED:['已退出','Exited'],FAILED:['运行失败','Failed'],STOP_BLOCKED:['停止受阻','Stop blocked'],DISPLAY_UNKNOWN:['画面状态待确认','Display unconfirmed'],DISCONNECTED:['未连接','Disconnected']};
  return names[phase]?.[language==='en'?1:0]||phase;
}
export function sessionSummary(view={}){
  const facts=(view.rows||[]).filter(r=>r.row_kind==='FACT_PREFIX');
  const pending=(view.submitted||[]).filter(r=>!(view.receipts||[]).some(x=>x.request_id===r.request_id));
  const products=view.product_statuses;
  return {products:(view.orders||[]).length,received:Array.isArray(products)?products.filter(p=>Number.isFinite(p.received_h)).length:null,
    running:facts.filter(r=>r.end_status==='OPEN').length,pending:pending.length,blocked:!!view.full_schedule?.failure};
}
export function archiveProgress(view={}){
  const m=view.reader_metrics||{};
  if(!Number.isFinite(m.total_bytes)||m.total_bytes<=0)return null;
  return Math.max(0,Math.min(100,Math.floor(100*m.byte_cursor/m.total_bytes)));
}
export function errorHelp(error,language='zh'){
  const en=language==='en',s=String(error||'');
  const rules=[
    [/PERSON_RETURN_LOCATION/,'请核对人员返回位置','Check the person’s return location','选择已有人员，等待已核验的位置显示后重新核对参数。','Select an existing person and wait for the verified location before reviewing the request.'],
    [/STARTUP_CHECK_FAILED|CPU_PYTHON|WinError 2|WORKER_START_FAILED/,'启动环境或文件不可用','Startup files or environment are unavailable','运行自检，按列出的具体路径补齐环境或重新完整解压。CPU 模式无需安装 Isaac。','Run diagnostics and repair the named path. CPU mode does not require Isaac.'],
    [/NATIVE_SESSION_UNAVAILABLE/,'当前没有可定位的三维会话','No connected 3D session','CPU 和历史存档使用甘特浏览；连接三维会话后才能使用相机定位。','Browse the timeline in CPU/archive mode. Camera actions require a connected 3D session.'],
    [/READ_ONLY|WAIT_FOR_VERIFIED|DISPLAY_UNKNOWN|STALE/,'当前状态暂不允许业务操作','Business changes are unavailable','核对历史/实时模式与连接状态；等待已验证的新数据，保留原请求 ID。','Check the session mode and connection; wait for verified data and keep the original request ID.'],
    [/REQUEST_BUSY|WAIT_FOR_PENDING|QUERY_ORIGINAL/,'上一项操作仍在处理中','The previous action is pending','在请求记录中查询原操作，不要重复提交。','Check the original request in Receipts instead of submitting again.'],
    [/EXAMPLE_MISSING/,'找不到示例存档','Example archive is missing','请完整解压新版包，或通过“打开会话”选择已有存档。','Extract the complete package or use Open session to select an archive.'],
    [/EXPORT|NO_VERIFIED_FRAME/,'导出尚未完成','Export was not completed','先加载已核验数据，并选择当前用户可写的文件位置。','Load verified data and choose a writable destination.'],
  ];
  const r=rules.find(x=>x[0].test(s));
  return {title:r?r[en?2:1]:en?'This action could not be completed':'这项操作未能完成',help:r?r[en?4:3]:en?'Review the details, run diagnostics, and keep your current session.':'查看详细原因或运行自检；保留当前会话后再处理。',raw:s};
}
export function receiptLabel(value,language='zh'){
  const names={REGISTERED:['产品已登记','Products registered'],ORDER_UPDATED:['订单属性已更新','Order attributes updated'],PERSON_ARRIVED:['人员已到岗','Person arrived'],DEVICE_FAILED:['设备故障已生效','Device failure applied'],DEVICE_REPAIRED:['设备维修已生效','Device repair applied'],ACCEPTED:['已接纳','Accepted'],APPLIED:['已生效','Applied'],REJECTED:['已拒绝','Rejected'],PENDING:['处理中','Pending'],SUBMITTED:['已发送','Submitted'],COMPLETED:['已完成','Completed'],FAILED:['失败','Failed'],UNKNOWN:['待确认','Unconfirmed']};
  return names[value]?.[language==='en'?1:0]||value||'—';
}
export function overviewLanes(items,language='zh'){
  const groups=new Map();
  for(const item of items.filter(i=>!i.heading&&!i.detail&&!i.waiting)){
    const id=item.product_id||item.rows[0]?.product_id||item.rows[0]?.resource_id||item.id;
    if(!groups.has(id))groups.set(id,{id:'overview:'+id,name:id,rows:[],height:38});
    groups.get(id).rows.push(...item.rows);
  }
  return [...groups.values()].map(x=>({...x,name:x.name+' · '+(language==='en'?'segments':'工序段')}));
}
