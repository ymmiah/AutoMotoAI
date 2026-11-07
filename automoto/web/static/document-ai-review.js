/* Document Assistant v3: approval boundaries for local-model suggestions.
   No automatic source edits or remote API/model calls. */
export const REVIEW_LIMIT = 12000;
export const REVIEW_MODES = Object.freeze(["proofread", "rewrite", "summary"]);

export function editableReviewRequest(mode,markdown,selectionStart,selectionEnd) {
  if(!REVIEW_MODES.includes(mode))throw Error("Unknown document AI action.");
  if(typeof markdown!=="string")throw Error("An editable document is required.");
  if(!Number.isInteger(selectionStart)||!Number.isInteger(selectionEnd)||
      selectionStart<0||selectionEnd<selectionStart||selectionEnd>markdown.length)
    throw Error("Invalid text selection.");
  const selected=selectionEnd>selectionStart;
  const start=selected?selectionStart:0,end=selected?selectionEnd:markdown.length;
  const text=markdown.slice(start,end);
  if(!text.trim())throw Error("Enter text before requesting a review.");
  if(text.length>REVIEW_LIMIT)throw Error("Select a section of at most 12,000 characters.");
  return {mode,markdown,start,end,selected,text};
}

export function applyReviewedProposal(currentMarkdown,snapshot,review){
  if(typeof currentMarkdown!=="string"||typeof snapshot?.markdown!=="string"||
     currentMarkdown!==snapshot.markdown)
    throw Error("The document changed after this review. Run the review again.");
  if(!review||!["proofread","rewrite"].includes(review.mode)||
      review.applied!==false||review.requires_approval!==true||
      typeof review.proposal!=="string"||!review.proposal.trim())
    throw Error("There is no approved replacement text.");
  const selection=review.selection;
  if(!selection||selection.start!==snapshot.start||selection.end!==snapshot.end||
     selection.start<0||selection.end>currentMarkdown.length||
     selection.end<selection.start)
    throw Error("Reviewed selection does not match the current document.");
  const result=currentMarkdown.slice(0,selection.start)+review.proposal+
    currentMarkdown.slice(selection.end);
  if(result.length>120000)throw Error("Review exceeds the document size limit.");
  return {markdown:result,start:selection.start,end:selection.start+review.proposal.length};
}

export function supportedEvidence(review,source){
  if(!Array.isArray(review?.evidence)||typeof source!=="string")return [];
  return review.evidence.filter(e=>typeof e?.quote==="string"&&
    typeof e?.claim==="string"&&Number.isInteger(e.offset)&&e.offset>=0&&
    source.slice(e.offset,e.offset+e.quote.length)===e.quote).slice(0,8);
}

export async function sourceDigest(text){
  // Browser secure context (localhost/Electron app): cryptographic precondition
  // rejects stale previews at the server rather than guessing from file names.
  if(!globalThis.crypto?.subtle)throw Error("Local AI requires a secure localhost desktop session.");
  const bytes=new TextEncoder().encode(text);
  const buffer=await globalThis.crypto.subtle.digest("SHA-256",bytes);
  return Array.from(new Uint8Array(buffer),n=>n.toString(16).padStart(2,"0")).join("");
}
