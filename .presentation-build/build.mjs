import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {Presentation, PresentationFile} from 'file:///C:/Users/dhruv/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs';

const root = 'C:/Users/dhruv/Desktop/Data House Data Hackathon';
const skill = 'C:/Users/dhruv/.codex/plugins/cache/openai-primary-runtime/presentations/26.905.11957/skills/presentations';
const temp = path.join(root,'.presentation-build');
const out = path.join(root,'output','presentation');
await fs.mkdir(out,{recursive:true});
const {resolvePresentationFont,finalizePresentation} = await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const font = resolvePresentationFont({fontFamily:'Arial'});
const deck = Presentation.create({slideSize:{width:1280,height:720}});
const navy='#142D4E', teal='#0A9B90', white='#FFFFFF', light='#F4F7FA', muted='#52647C';
const notes=[];
function text(s,t,x,y,w,h,size=30,color=navy,bold=false){
  const box=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
  box.text=t;
  box.text.style={typeface:font,fontSize:size,color,bold,autoFit:'none'};
  return box;
}
function slide(title,dark=false){
  const s=deck.slides.add(); s.background.fill=dark?navy:light;
  if(title) text(s,title,76,60,1128,90,46,dark?white:navy,true);
  return s;
}
function note(s,title,timing,script,sources){
  s.speakerNotes.textFrame.setText(`${timing}\n\n${script}\n\nSources (not spoken):\n${sources}`);
  notes.push({title,timing,script});
}

let s=slide('',true);
text(s,'SiteWise UK',76,105,1120,115,88,white,true);
text(s,'Planning checks before committing\nto a property or design',80,253,1110,130,43,'#57D3C4',false);
text(s,'A protected tree can change the whole building layout',80,493,1090,88,31,white);
text(s,'House London #2 Data Hackathon',80,638,1090,35,23,'#ADC3DB');
note(s,'The problem','0:00–0:25',
  'SiteWise UK helps people understand planning considerations before committing to a property. The idea came from my family looking at a development site. We discovered that a protected tree complicated the building layout. For buyers unfamiliar with the UK planning process, important information is scattered across council documents, maps and previous applications. We wanted to bring those checks forward.',
  'Problem story: project founder\'s account supplied in the conversation. Product scope: README.md and Docs/COUNCIL_POLICY.md.');

s=slide('A site screen before the design');
text(s,'01',78,189,70,55,34,teal,true);
text(s,'Choose a location and describe the proposal',175,190,1020,58,32,navy,true);
text(s,'02',78,300,70,55,34,teal,true);
text(s,'Retrieve council guidance and planning evidence',175,301,1020,58,32,navy,true);
text(s,'03',78,411,70,55,34,teal,true);
text(s,'Review design checks with links to the sources',175,412,1020,58,32,navy,true);
text(s,'Optional AI explains the evidence after retrieval',175,537,1020,55,27,muted);
note(s,'The solution','0:25–0:45',
  'You choose a location and describe your proposal. SiteWise retrieves council guidance, checks available spatial layers and searches nearby or similar applications. The dashboard explains what needs investigation and links back to the evidence. An optional AI summary explains those results, while missing information stays explicitly unknown.',
  'Implementation: sitewise/evidence.py, sitewise/policies.py, sitewise/llm.py, sitewise/webapp.py.');

s=slide('The data behind the screen');
const rows=[
 ['London planning CSV, 2022–2025','Application descriptions and historical decisions'],
 ['GLA Local Plan ArcGIS','Published local-plan spatial layers'],
 ['Planning Data API','Council boundaries and optional constraint queries'],
 ['Official council webpages and PDFs','Relevant policy text and application guidance'],
];
rows.forEach((r,i)=>{text(s,r[0],78,185+i*96,515,70,29,navy,true);text(s,r[1],635,185+i*96,570,76,27,muted);});
text(s,'Council-text pilot: Wandsworth, Westminster and Lambeth',78,625,1130,42,25,teal,true);
note(s,'The data','0:45–1:10',
  'We combine the supplied London planning dataset with public GLA spatial layers and the Planning Data API. Official council webpages and PDFs add the actual guidance relevant to a proposal. That distinction matters: a map designation alone does not explain the rule. Our council-text pilot currently covers Wandsworth, Westminster and Lambeth, plus selected London-wide policies.',
  'Supplied file: Data/raw/foundations_london_housing_2022_2025_20260810T013626Z.csv\nGLA: https://data.london.gov.uk/dataset/planning-local-plan-data-2zjmn\nPlanning Data: https://www.planning.data.gov.uk/\nCouncil-source registry and exact URLs: sitewise/policy_sources.py\nCoverage: Docs/COUNCIL_POLICY.md.');

s=slide('Previous hackathon work');
text(s,'0-the-spike',78,179,440,62,39,teal,true);
text(s,'Adapted comparable-case retrieval\nusing TF-IDF and cosine similarity',535,178,660,91,29,navy);
text(s,'ConfidentPlanner',78,323,440,62,34,navy,true);
text(s,'Reference for spatial checks and nearby applications',535,322,660,86,29,muted);
text(s,'0-RIBS',78,453,440,62,34,navy,true);
text(s,'Reference for data validation and caching',535,454,660,82,29,muted);
text(s,'Independent implementations for reference-only code. No inherited approval model.',78,614,1130,72,23,teal,true);
note(s,'Legacy project credits','1:10–1:35',
  'We built on the comparable-application approach from 0-the-spike, adapting TF-IDF and cosine similarity to our CSV. ConfidentPlanner informed spatial and nearby searches, while 0-RIBS informed validation and caching. We independently implemented concepts where licensing restricted copying. We did not import their approval models, and a similarity score never represents an approval probability.',
  'Source of truth: LEGACY_REUSE.md\nhttps://github.com/house-london/0-the-spike (MIT licence)\nhttps://github.com/athuler/ConfidentPlanner (implementation reference only)\nhttps://github.com/house-london/0-RIBS (implementation reference only)\nImplementation: sitewise/similarity.py and sitewise/planning.py.');

s=slide('Live demo',true);
text(s,'A rear extension and two new homes',80,216,1110,100,48,'#57D3C4',true);
text(s,'Which council guidance matters for this proposal?',80,359,1080,88,36,white);
text(s,'Location search, evidence and practical next checks',80,487,1090,65,28,'#ADC3DB');
text(s,'Preliminary screening. Council verification and professional advice remain essential.',80,631,1120,52,23,white);
note(s,'Demo handover','1:35–1:50',
  'Let me show you a proposal for a rear extension and two new homes. I will select a location, review the council guidance and show which issues still need checking. This is preliminary screening to support a better planning conversation.',
  'Live demonstration of the local SiteWise UK web application. The example is illustrative and does not assert the existence of a specific residential site.');

const candidate=path.join(temp,'candidate-v2.pptx');
await (await PresentationFile.exportPptx(deck)).save(candidate);
for(let i=0;i<deck.slides.items.length;i++){
  const png=await deck.export({slide:deck.slides.items[i],format:'png',scale:1});
  await fs.writeFile(path.join(temp,`slide-${i+1}.png`),new Uint8Array(await png.arrayBuffer()));
}
const script='# SiteWise UK: 1 minute 50 second introduction\n\nAdvance at the times below, then switch to the website. Sources are in the PowerPoint speaker notes.\n\n'+notes.map((n,i)=>`## Slide ${i+1}: ${n.title} (${n.timing})\n\n${n.script}\n`).join('\n');
await fs.writeFile(path.join(out,'SiteWise_Speaking_Notes.md'),script);
const result=await finalizePresentation({
  workspaceDir:root,candidatePath:candidate,finalPath:path.join(out,'SiteWise_UK_Presentation.pptx'),
  pythonExecutable:'C:/Users/dhruv/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',
  integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),
  layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
  layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit'],
  explicitTotalSlideCount:5,fontPolicy:{basis:'design',families:[font]},
  verifyArtifactToolImport:true,receiptPath:path.join(temp,'validation-v2.json')
});
console.log(JSON.stringify({result,font,words:notes.reduce((n,x)=>n+x.script.split(/\s+/).length,0)}));
