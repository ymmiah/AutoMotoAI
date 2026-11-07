/* Pure, dependency-free Document Assistant editor model: structured Markdown,
   escaped preview, table operations and bounded cross-field undo/redo. */

const clone=value=>JSON.parse(JSON.stringify(value));
export const DEFAULT_LAYOUT=Object.freeze({
  page_size:"A4",orientation:"portrait",margins_cm:2.5,font:"Calibri",
  font_size:11,line_spacing:1.15,heading_color:"#1F3864",page_numbers:true
});

export function layoutOptions(options={}){
  return {...DEFAULT_LAYOUT,...Object.fromEntries(Object.entries(options||{})
    .filter(([key])=>Object.hasOwn(DEFAULT_LAYOUT,key)))};
}

export function createDocumentHistory(initial,maxSteps=80){
  let current=clone(initial),past=[],future=[],lastKind="",lastTime=-Infinity;
  const commit=(next,{kind="edit",time=Date.now(),coalesce=false}={})=>{
    const saved=clone(next);
    if(JSON.stringify(saved)===JSON.stringify(current))return false;
    if(!coalesce||lastKind!==kind||time-lastTime>700||time<lastTime){
      past.push(clone(current));if(past.length>maxSteps)past.shift();
    }
    current=saved;future=[];lastKind=coalesce?kind:"";lastTime=time;
    return true;
  };
  const undo=()=>{
    if(!past.length)return null;
    future.push(clone(current));current=past.pop();
    lastKind="";lastTime=-Infinity;
    return clone(current);
  };
  const redo=()=>{
    if(!future.length)return null;
    past.push(clone(current));current=future.pop();
    lastKind="";lastTime=-Infinity;
    return clone(current);
  };
  const reset=next=>{current=clone(next);past=[];future=[];lastKind="";lastTime=-Infinity;};
  const state=()=>({canUndo:past.length>0,canRedo:future.length>0,
    value:clone(current),undoDepth:past.length});
  return {commit,undo,redo,reset,state};
}

export function documentOutline(markdown){
  const headings=[],re=/^(#{1,6})[ \t]+([^\r\n]+)$/gm;
  let match;
  while((match=re.exec(markdown))!==null){
    headings.push({level:match[1].length,text:match[2].trim(),
      offset:match.index,end:match.index+match[0].length});
    if(headings.length>=200)break;
  }
  return headings;
}

export function formatHeading(markdown,start,end,level){
  if(!Number.isInteger(level)||level<1||level>6)return null;
  const a=markdown.lastIndexOf("\n",Math.max(0,start-1))+1;
  const last=markdown.indexOf("\n",end);
  const b=last===-1?markdown.length:last;
  const line=markdown.slice(a,b).replace(/^#{1,6}[ \t]*/,"").trim();
  const replacement="#".repeat(level)+" "+(line||"Section heading");
  return {value:markdown.slice(0,a)+replacement+markdown.slice(b),
    start:a,end:a+replacement.length};
}

export function createTable(markdown,start,end){
  const table="| Column A | Column B | Column C |\n"+
    "| --- | --- | --- |\n"+
    "| Value 1 | Value 2 | Value 3 |\n"+
    "| Value 4 | Value 5 | Value 6 |";
  const before=markdown.slice(0,start);
  const after=markdown.slice(end);
  const insert=(before&&!before.endsWith("\n\n")?"\n\n":"")+
    table+(after&&!after.startsWith("\n\n")?"\n\n":"");
  return {value:before+insert+after,start:before.length+insert.indexOf(table),
    end:before.length+insert.indexOf(table)+table.length};
}

export function appendTableRow(markdown,cursor){
  const lines=markdown.split("\n");
  let start=0,active=-1;
  for(let i=0;i<lines.length;i++){
    const end=start+lines[i].length;
    if(cursor>=start&&cursor<=end && /^\s*\|.*\|\s*$/.test(lines[i]))active=i;
    start=end+1;
  }
  if(active<0)return null;
  let first=active,last=active;
  while(first>0&&/^\s*\|.*\|\s*$/.test(lines[first-1]))first--;
  while(last+1<lines.length&&/^\s*\|.*\|\s*$/.test(lines[last+1]))last++;
  const header=lines[first].trim().replace(/^\||\|$/g,"").split("|");
  if(header.length<2||header.length>12)return null;
  const cells=header.map(()=>" New value ");
  const newRow="|"+cells.join("|")+"|";
  lines.splice(last+1,0,newRow);
  const value=lines.join("\n");
  const offset=lines.slice(0,last+1).join("\n").length+(last>=0?1:0);
  return {value,start:offset,end:offset+newRow.length};
}

export function renderDocumentPreview(markdown,escape){
  const lines=markdown.split(/\r?\n/).slice(0,1800);
  const parts=[];let inList=false;
  const inline=s=>escape(s).replace(/\*\*([^*\n]+)\*\*/g,"<strong>$1</strong>");
  for(let i=0;i<lines.length;i++){
    const raw=lines[i],line=raw.trim(),heading=/^(#{1,6})\s+(.+)/.exec(line);
    const bullet=/^[-*+]\s+(.+)/.exec(line);
    if(inList&&!bullet){parts.push("</ul>");inList=false;}
    if(!line){parts.push('<div class="da-blank"></div>');continue;}
    if(heading){
      const n=Math.min(6,heading[1].length);
      parts.push("<h"+n+">"+inline(heading[2])+"</h"+n+">");continue;
    }
    if(bullet){
      if(!inList){parts.push("<ul>");inList=true;}
      parts.push("<li>"+inline(bullet[1])+"</li>");continue;
    }
    if(/^\|.*\|$/.test(line)){
      const rows=[];
      while(i<lines.length&&/^\|.*\|$/.test(lines[i].trim())&&rows.length<60){
        const cells=lines[i].trim().slice(1,-1).split("|").map(cell=>cell.trim());
        if(cells.length>12){
          // Consume malformed/wide rows rather than revisiting the same
          // source line indefinitely; always render their text escaped.
          parts.push("<p>"+inline(lines[i])+"</p>");
          i++;break;
        }
        if(!cells.every(cell=>/^:?-{2,}:?$/.test(cell)))rows.push(cells);
        i++;
      }
      i--;
      if(rows.length){
        parts.push('<table class="da-table"><tbody>');
        for(let j=0;j<rows.length;j++){
          parts.push("<tr>"+rows[j].map(cell=>j===0?"<th>"+inline(cell)+"</th>":
            "<td>"+inline(cell)+"</td>").join("")+"</tr>");
        }
        parts.push("</tbody></table>");
      }
      continue;
    }
    if(line.startsWith(">"))parts.push("<blockquote>"+inline(line.slice(1).trim())+"</blockquote>");
    else if(line==="---"||line==="***")parts.push("<hr>");
    else parts.push("<p>"+inline(line)+"</p>");
  }
  if(inList)parts.push("</ul>");
  return parts.join("");
}
