import test from 'node:test';
import assert from 'node:assert/strict';
import {rowForEntity,selectedEntity,restoreSelection,synchronization,requestSteps,viewCamera,requestTargets} from '../src/linkage.mjs';
import {sceneSelectionState,relatesToSelection} from '../src/linkage.mjs';

test('native multi-selection retains every entity and clears stale work on empty or unmapped picks',()=>{
 const rows=[{row_id:'a',person_id:'W1'},{row_id:'b',product_id:'P2'},{row_id:'c',product_id:'P3'}];
 const selected=sceneSelectionState(rows,{entity_ids:['W1','P2','W1'],paths:['/W1','/P2']},rows[1]);
 assert.deepEqual(selected.ids,['W1','P2']);assert.equal(selected.primary,rows[1]);
 assert.deepEqual(rows.map(r=>relatesToSelection(r,selected.ids)),[true,true,false]);
 assert.equal(sceneSelectionState(rows,{entity_ids:[]},rows[0]).primary,null);
 assert.equal(sceneSelectionState(rows,{entity_ids:['FLOOR']},rows[0]).primary,null);
 assert.equal(sceneSelectionState(rows,{paths:['/World/Ground']},rows[0]).paths.length,1);
});

test('person selection does not silently focus the product first',()=>{
  assert.equal(selectedEntity({person_id:'W',product_id:'P'},[{id:'W',paths:['/World/W']},{id:'P',paths:['/World/P']}]),'W');
});
test('native object selects active actual work before a future plan',()=>{
  const rows=[{row_id:'future',product_id:'P',schedule_state:'PLANNED'},{row_id:'actual',product_id:'P',schedule_state:'ACTUAL',end_status:'OPEN'}];
  assert.equal(rowForEntity(rows,['P'],null).row_id,'actual');
});
test('plan updates preserve stable work selection, removed work stays explicitly historical',()=>{
  const old={row_id:'v1',work_key:'A',schedule_state:'PLANNED'};
  assert.equal(restoreSelection([{row_id:'v2',work_key:'A',schedule_state:'PLANNED'}],old).row_id,'v2');
  assert.equal(restoreSelection([],old).historical_selection,true);
});
test('fresh frames with different revisions are not advertised as synchronized',()=>{
  assert.equal(synchronization({backend:'ISAAC',envelope:{state_revision:2}},{frame:{fresh:true,source_state_revision:1}},'RUNNING'),'UPDATING');
  assert.equal(synchronization({}, {}, 'SAVED_READ_ONLY'),'ARCHIVE');
});
test('accepted requests do not fabricate execution or scene effects',()=>{
  const s=requestSteps({receipts:[{request_id:'R',status:'ACCEPTED'}],verified_full_schedule:{version:2}}, {request_id:'R',target_id:'P'}, {entities:[]});
  assert.equal(s.status,'ACCEPTED');assert.deepEqual(s.facts,[]);assert.equal(s.sceneMapped,false);assert.equal(s.before,null);
});

test('order change resolves the registered product, without claiming execution',()=>{
 const request={request_id:'R',target_id:'ORDER-X'};
 const view={orders:[{id:'PRODUCT-2',order_id:'ORDER-X'}],business_results:[{request_id:'R',status:'REGISTERED',product_ids:['PRODUCT-2']}],rows:[{row_kind:'MARKER',schedule_state:'ACTUAL',target_id:'ORDER-X'}]};
 const step=requestSteps(view,request,{entities:[{id:'PRODUCT-2',paths:['/World/Product2']}]});
 assert.equal(step.sceneMapped,true);assert.deepEqual(step.targets,['PRODUCT-2','ORDER-X']);assert.equal(step.actualRows,0);
});

test('camera label follows confirmed frame actions rather than failed requests',()=>{
 assert.equal(viewCamera({accepted:false,action:'camera',camera:'Top'},'Overview'),'Overview');
 assert.equal(viewCamera({accepted:true,action:'focus'},'Overview'),'custom');
 assert.equal(viewCamera({accepted:true,action:'camera',camera:'Top'},'custom'),'Top');
});

test('registered invisible products are distinguished from visible scene objects',()=>{
 const r={request_id:'R',target_id:'ORDER-X'};const v={orders:[{id:'P2',order_id:'ORDER-X'}]};
 const step=requestSteps(v,r,{entities:[{id:'P2',paths:['/World/P2'],visible:false}]});
 assert.equal(step.sceneMapped,true);assert.equal(step.sceneVisible,false);
 assert.equal(selectedEntity({product_id:'P2',equipment:['FORK']},[{id:'P2',paths:['/World/P2'],visible:false},{id:'FORK',paths:['/World/Fork'],visible:true}]),'FORK');
});

test('closed native session and typed request targets stay explicit',()=>{
 assert.equal(synchronization({}, {}, 'EXITED'),'ENDED');
 const objects={O:{kind:'order'},P:{kind:'person'},D:{kind:'device'}};
 assert.deepEqual(requestTargets(objects,'ORDER_UPDATE'),['O']);
 assert.deepEqual(requestTargets(objects,'DEVICE_FAIL'),['D']);
 assert.deepEqual(requestTargets(objects,'PERSON_ARRIVE'),[]);
});
