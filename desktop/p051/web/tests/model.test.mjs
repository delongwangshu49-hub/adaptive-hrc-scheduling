import test from 'node:test';
import assert from 'node:assert/strict';
import {interval,lanesFor,makePayload,laneLabel} from '../src/model.mjs';
test('unknown intervals do not fabricate a duration',()=>{assert.equal(interval({}),null);assert.deepEqual(interval({start_h:2}),[2,2]);});
test('resource view expands shared delivered work and preserves identity',()=>{const r={row_id:'r',work_key:'w',operation_id:'OP',roles:[{person_id:'W1'},{person_id:'W2'}],schedule_state:'ACTUAL'};const lanes=lanesFor([r],{mode:'resource'});assert.equal(lanes.length,2);assert.ok(lanes.every(l=>l.rows[0]===r));});
test('candidate and adopted are distinct from schedule state',()=>{const rows=[{row_id:'a',operation_id:'OP',schedule_state:'TENTATIVE',proposal_state:'SUPERSEDED'},{row_id:'b',operation_id:'OP',schedule_state:'COMMITTED',proposal_state:'CANDIDATE'}];assert.equal(lanesFor(rows)[0].rows.length,1);assert.equal(lanesFor(rows,{compare:true})[0].rows.length,2);});
test('return form cannot reset historical fatigue',()=>{assert.deepEqual(makePayload('PERSON_RETURN',{target_id:'W1',arrival_location:'F1',initial_f:0}),{arrival_location:'F1',scene_entity_id:'W1'});});
test('urgent flag and quantity remain explicit typed fields',()=>{assert.deepEqual(makePayload('ORDER_CREATE',{template_id:'SR-W1',quantity:'2',due_sim_h:'5',priority:'URGENT'}),{template_id:'SR-W1',quantity:2,due_sim_h:5,priority:'URGENT',material_plan_id:'TEMPLATE-JIT-v1'});});
test('numeric error cannot become JSON null business input',()=>{assert.throws(()=>makePayload('REST_REQUEST',{duration_h:'not a number'}));});

test('order metadata edits carry typed due time and priority without creation fields',()=>{assert.deepEqual(makePayload('ORDER_UPDATE',{target_id:'ORDER-1',due_sim_h:'200',priority:'URGENT',quantity:'7'}),{due_sim_h:200,priority:'URGENT'});assert.throws(()=>makePayload('ORDER_UPDATE',{due_sim_h:'bad',priority:'NORMAL'}));});

test('operation view keeps operation work and event points without person occupancy lanes',()=>{const rows=[{row_id:'o',operation_id:'OP',row_kind:'PLAN'},{row_id:'p',person_id:'W1',row_kind:'PERSON_INTERVAL'},{row_id:'e',target_id:'W1',row_kind:'MARKER',canonical_lane:'events'}];assert.deepEqual(lanesFor(rows).map(x=>x.id),['events','OP']);assert.deepEqual(lanesFor(rows,{mode:'resource'}).map(x=>x.id),['W1']);});
test('explicit previous proposal filter is visible independently of compare toggle',()=>{const rows=[{row_id:'a',operation_id:'OP',proposal_state:'SUPERSEDED',schedule_state:'TENTATIVE'}];assert.equal(lanesFor(rows,{states:['SUPERSEDED']})[0].rows.length,1);});

test('compact labels expose work suffix without changing the original lane identity',()=>{assert.equal(laneLabel('PRODUCT-1.COAT-W1'),'1·COAT-W1');assert.equal(laneLabel('SERVICE-135-P1-WALK'),'S135·P1-WALK');const r={row_id:'a',operation_id:'PRODUCT-1.COAT-W1'};assert.equal(lanesFor([r])[0].id,r.operation_id);});
