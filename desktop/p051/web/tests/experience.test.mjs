import test from 'node:test';
import assert from 'node:assert/strict';
import {sessionSummary,archiveProgress,errorHelp,overviewLanes} from '../src/experience.mjs';

test('summary never counts a planned completion as a received product',()=>{
  const result=sessionSummary({orders:[{id:'p'}],rows:[{row_kind:'FULL_PLAN',end_status:'CLOSED'},{row_kind:'FACT_PREFIX',end_status:'OPEN'}],product_statuses:[{received_h:null}],submitted:[{request_id:'r'}],receipts:[]});
  assert.equal(result.received,0);assert.equal(result.running,1);assert.equal(result.pending,1);
  assert.equal(sessionSummary({}).received,null);
});
test('receipt and actual receipt time remain independent',()=>{
  assert.equal(sessionSummary({product_statuses:[{received_h:0},{received_h:null},{received_h:50}]}).received,2);
  assert.equal(sessionSummary({submitted:[{request_id:'r'}],receipts:[{request_id:'r',status:'REJECTED'}]}).pending,0);
});
test('historical reading progress is explicit and bounded',()=>{
  assert.equal(archiveProgress({}),null);assert.equal(archiveProgress({reader_metrics:{byte_cursor:25,total_bytes:100}}),25);
  assert.equal(archiveProgress({reader_metrics:{byte_cursor:110,total_bytes:100}}),100);
});
test('WinError 2 recovery does not prescribe Isaac for CPU',()=>{
  assert.match(errorHelp('WORKER_START_FAILED WinError 2').help,/CPU.*无需.*Isaac/);
  assert.match(errorHelp('NATIVE_SESSION_UNAVAILABLE','en').help,/connected 3D session/);
  assert.equal(errorHelp('unknown code').raw,'unknown code');
});
test('overview preserves actual interval objects and filters out empty headings',()=>{
  const actual={row_id:'a',product_id:'p',start_h:1,end_h:1.001},plan={row_id:'b',product_id:'p',start_h:5,end_h:6};
  const lanes=overviewLanes([{id:'heading',heading:true,rows:[]},{id:'a',rows:[actual]},{id:'b',rows:[plan]}]);
  assert.equal(lanes.length,1);assert.deepEqual(lanes[0].rows,[actual,plan]);assert.equal(lanes[0].rows[0].end_h,1.001);
});
