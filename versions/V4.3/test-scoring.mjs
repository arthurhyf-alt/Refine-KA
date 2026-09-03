import assert from 'node:assert/strict';
import { DIMENSIONS, COMPANY_DIMENSIONS, effectiveScore, scoreIndustry, scoreCompany, parseCsv } from './scoring.js';

assert.equal(effectiveScore(100, 1), 100);
assert.equal(effectiveScore(100, 0), 50);
assert.equal(effectiveScore(null, 1), 50);

const record = { metrics: Object.fromEntries(DIMENSIONS.map(({key}) => [key, {score:100, confidence:1}])) };
const weights = Object.fromEntries(DIMENSIONS.map(({key}) => [key, 1]));
assert.equal(scoreIndustry(record,weights).totalScore,100);
assert.equal(scoreIndustry(record,weights).coverage,1);

const companyRecord={metrics:Object.fromEntries(COMPANY_DIMENSIONS.map(({key},index)=>[key,{score:index?0:100,confidence:1}]))};
const companyWeights=Object.fromEntries(COMPANY_DIMENSIONS.map(({key},index)=>[key,index?0:100]));
assert.equal(scoreCompany(companyRecord,companyWeights).totalScore,100);
assert.equal(scoreCompany(companyRecord,companyWeights).coverage,1);
assert.equal(scoreCompany(companyRecord,companyWeights).formal,false);

const sourcedCompany={metrics:Object.fromEntries(COMPANY_DIMENSIONS.map(({key})=>[key,{score:80,confidence:1,evidenceItems:[{url:'https://example.com/a'},{url:'https://example.org/b'}]}]))};
assert.equal(scoreCompany(sourcedCompany).formal,true);

const parsed=parseCsv('industry,region,demand_score,demand_confidence\nSemiconductor,Shanghai,80,0.9');
assert.equal(parsed.length,1);
assert.equal(parsed[0].industry,'Semiconductor');
assert.equal(parsed[0].metrics.demand.score,80);
console.log('scoring tests passed');
