/* V15: local-only database inspector and read-only SQL/GraphQL review. */
export function mountDeveloperData({api,host,getProject,editor}) {
  const root=host.querySelector("#dsDataRoot");
  const BASE="/api/developer/studio";
  root.innerHTML=
    '<section class="ds-data-panel" aria-label="SQL database and GraphQL safe review">'+
    '<div class="ds-data-head"><h3>SQL, data & GraphQL · V15</h3>'+
    '<span class="ds-readonly">SNAPSHOT ONLY · NO LIVE DATABASE WRITES</span></div>'+
    '<div class="ds-data-body">'+
      '<p class="ds-footnote">Inspect one approved SQLite file through a temporary private copy. Database writes, live credentials, migrations against your original file and remote GraphQL requests are not available.</p>'+
      '<div class="ds-data-controls">'+
       '<label for="dsDataDB">SQLite file (.db, .sqlite)</label>'+
       '<input id="dsDataDB" class="input" spellcheck="false" placeholder="data/project.db" maxlength="1024">'+
       '<button id="dsDataSchema" class="btn sm" disabled type="button">Inspect SQLite schema</button></div>'+
      '<label for="dsDataQuery">Read-only SQL query</label>'+
      '<textarea id="dsDataQuery" class="input" rows="3" spellcheck="false" maxlength="8000" placeholder="SELECT name FROM records WHERE id = ?"></textarea>'+
      '<div class="ds-data-controls">'+
       '<label for="dsDataArgs">Parameters (JSON array)</label>'+
       '<input id="dsDataArgs" class="input" spellcheck="false" value="[]" maxlength="2048">'+
       '<button id="dsDataRun" class="btn sm" disabled type="button">Run on temporary snapshot</button></div>'+
      '<label for="dsDataMigration">Migration preview (one CREATE/ALTER ADD COLUMN/DROP INDEX)</label>'+
      '<textarea id="dsDataMigration" class="input" rows="3" spellcheck="false" maxlength="8000" placeholder="ALTER TABLE records ADD COLUMN reviewed INTEGER"></textarea>'+
      '<button id="dsDataPreview" class="btn sm" disabled type="button">Preview migration & rollback</button>'+
      '<div class="ds-data-controls">'+
       '<label for="dsDataDialect">Static dialect / GraphQL</label>'+
       '<select id="dsDataDialect" class="input">'+
         '<option value="graphql">GraphQL</option><option value="sqlite">SQLite SQL file</option>'+
         '<option value="postgresql">PostgreSQL SQL file</option><option value="mysql">MySQL SQL file</option></select>'+
       '<label for="dsDataSchemaFile">Schema file (.graphql, .gql or .sql)</label>'+
       '<input id="dsDataSchemaFile" class="input" maxlength="1024" spellcheck="false" placeholder="schema.graphql">'+
       '<button id="dsDataInspect" class="btn sm" disabled type="button">Inspect schema file</button></div>'+
       '<label for="dsDataOperation">GraphQL query (static review only)</label>'+
       '<textarea id="dsDataOperation" class="input" rows="3" maxlength="8192" spellcheck="false" placeholder="query { records { name } }"></textarea>'+
       '<button id="dsDataGraphQL" class="btn sm" disabled type="button">Check GraphQL root fields</button>'+
       '<p id="dsDataStatus" class="ds-footnote" role="status" aria-live="polite">Open a local project to inspect data files.</p>'+
       '<pre id="dsDataOutput" class="ds-data-output" tabindex="0" role="region" aria-label="Read-only query findings"></pre>'+
       '<p class="ds-footnote">SQLite queries are confined to a private copied database and denied writes by the SQLite authorizer. Migration previews execute and roll back only on that copy. GraphQL and PostgreSQL/MySQL inspection is static and does not connect to a server. Preview is not a safety guarantee for applying SQL to production.</p>'+
    '</div></section>';
  const el=id=>root.querySelector("#"+id);
  let busy=false,sequence=0;
  const project=()=>getProject()?.project||"";
  function show(message,error=false){
    const n=el("dsDataStatus");n.textContent=message;n.classList.toggle("ds-error",error);
  }
  function display(data){el("dsDataOutput").textContent=JSON.stringify(data,null,2);}
  function controls(){
    const ok=!!project()&&!busy;
    el("dsDataSchema").disabled=!ok||!el("dsDataDB").value.trim();
    el("dsDataRun").disabled=!ok||!el("dsDataDB").value.trim()||!el("dsDataQuery").value.trim();
    el("dsDataPreview").disabled=!ok||!el("dsDataDB").value.trim()||!el("dsDataMigration").value.trim();
    el("dsDataInspect").disabled=!ok||!el("dsDataSchemaFile").value.trim();
    el("dsDataGraphQL").disabled=!ok||el("dsDataDialect").value!=="graphql"||
      !el("dsDataSchemaFile").value.trim()||!el("dsDataOperation").value.trim();
  }
  async function go(endpoint,req,label){
    if(busy||!project())return;
    const selected=project(),id=++sequence;
    busy=true;controls();show(label);
    try{
      const result=await api(BASE+endpoint,req);
      if(id!==sequence||selected!==project()||!root.isConnected)return;
      display(result);
      show("Review complete. Original source not modified or deployed.");
    }catch(e){show("Data inspection rejected: "+e.message,true);}
    finally{busy=false;controls();}
  }
  const context=()=>({project:project(),path:el("dsDataDB").value.trim()});
  el("dsDataSchema").onclick=()=>void go("/sql/inspect",context(),"Reading private SQLite snapshot schema…");
  el("dsDataRun").onclick=()=>{
    let args;
    try{args=JSON.parse(el("dsDataArgs").value||"[]");if(!Array.isArray(args))throw Error("Expected JSON array");}
    catch(e){show("Parameters must be a JSON array.",true);return;}
    void go("/sql/query",{...context(),sql:el("dsDataQuery").value,params:args},
      "Reading a capped SQL result from a temporary private SQLite copy…");
  };
  el("dsDataPreview").onclick=()=>{
    if(!window.confirm("Preview this migration ONLY on a temporary database copy, "+
      "then verify rollback? This does not apply any SQL to your original database."))return;
    void go("/sql/migration-preview",{...context(),sql:el("dsDataMigration").value,
      confirmed:true,acknowledge_dry_run_only:true},
      "Testing migration and rollback on a throwaway SQLite copy…");
  };
  const dialect=()=>({project:project(),path:el("dsDataSchemaFile").value.trim(),
    dialect:el("dsDataDialect").value});
  el("dsDataInspect").onclick=()=>void go("/data/inspect",dialect(),
    "Inspecting static schema. No database or GraphQL server is contacted.");
  el("dsDataGraphQL").onclick=()=>void go("/data/graphql-review",
    {...dialect(),operation:el("dsDataOperation").value},
    "Checking GraphQL root-field declarations only; no server request.");
  for(const id of ["dsDataDB","dsDataQuery","dsDataArgs","dsDataMigration",
                    "dsDataDialect","dsDataSchemaFile","dsDataOperation"])
    el(id).addEventListener("input",controls);
  function fileChanged(path){
    if(/\.(?:db|sqlite|sqlite3)$/i.test(path||"")&&!el("dsDataDB").value)
      el("dsDataDB").value=path;
    if(/\.(?:graphql|gql|sql)$/i.test(path||"")&&!el("dsDataSchemaFile").value)
      el("dsDataSchemaFile").value=path;
    controls();
  }
  function projectChanged(){
    sequence++;busy=false;
    for(const id of ["dsDataDB","dsDataSchemaFile"])el(id).value="";
    el("dsDataOutput").textContent="";
    show("Open a local project to inspect SQL or GraphQL.");controls();
  }
  controls();
  return {projectChanged,fileChanged};
}
