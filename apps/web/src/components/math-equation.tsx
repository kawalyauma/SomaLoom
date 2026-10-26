"use client";
import {type ReactNode} from "react";

type Expr =
 | {kind:"row"; children:Expr[]}
 | {kind:"text"; value:string}
 | {kind:"fraction"; numerator:Expr; denominator:Expr}
 | {kind:"radical"; body:Expr}
 | {kind:"script"; base:Expr; script:Expr; mode:"sup"|"sub"}
 | {kind:"matrix"; rows:Expr[][]; brackets:string};

const symbols:Record<string,string> = {
 alpha:"α", beta:"β", gamma:"γ", theta:"θ", pi:"π", Delta:"Δ", mu:"μ",
 sin:"sin", cos:"cos", tan:"tan", log:"log", ln:"ln",
 times:"×", cdot:"·", div:"÷", pm:"±", neq:"≠", geq:"≥", leq:"≤",
 infty:"∞", sum:"∑", int:"∫", rightarrow:"→"
};
class MathParseError extends Error {}

class Parser {
 private index=0;
 constructor(private input:string){}
 private peek(){return this.input[this.index]||"";}
 private starts(text:string){return this.input.startsWith(text,this.index);}
 private group():Expr {
  if(this.peek()!=="{")throw new MathParseError("A required math group is missing.");
  this.index++;
  const result=this.seq("}");
  if(this.peek()!=="}")throw new MathParseError("An equation group is not closed.");
  this.index++;
  return result;
 }
 private atom():Expr {
  const char=this.peek();
  if(!char)throw new MathParseError("Unexpected end of equation.");
  if(char==="{")return this.group();
  if(char==="\\"){
   this.index++;
   const command=/^[A-Za-z]+/.exec(this.input.slice(this.index));
   if(!command){if(this.peek()){return {kind:"text",value:this.input[this.index++]};}throw new MathParseError("Invalid math escape.");}
   this.index+=command[0].length;
   const word=command[0];
   if(word==="frac"){return {kind:"fraction",numerator:this.group(),denominator:this.group()};}
   if(word==="sqrt"){
    if(this.peek()==="[")throw new MathParseError("Custom roots require native DOCX or editor review.");
    return {kind:"radical",body:this.group()};
   }
   if(word==="begin"){
    const start=this.index;
    this.group();
    const name=this.input.slice(start+1,this.index-1);
    if(!["matrix","pmatrix","bmatrix"].includes(name))throw new MathParseError("Unsupported matrix notation.");
    const stop="\\end{"+name+"}";
    const end=this.input.indexOf(stop,this.index);
    if(end<0)throw new MathParseError("Matrix is not closed.");
    const inside=this.input.slice(this.index,end);
    this.index=end+stop.length;
    const rows=inside.split("\\\\").map(row=>row.split("&").map(cell=>new Parser(cell.trim()).parse()));
    if(new Set(rows.map(row=>row.length)).size!==1)throw new MathParseError("Matrix columns are inconsistent.");
    return {kind:"matrix",rows,brackets:name==="pmatrix"?"()":name==="bmatrix"?"[]":""};
   }
   if(word==="left"||word==="right"){
    const value=this.peek();
    if(!value)throw new MathParseError("Missing delimiter.");
    this.index++;
    return {kind:"text",value};
   }
   if(word in symbols)return {kind:"text",value:symbols[word]};
   throw new MathParseError("Unsupported LaTeX command: "+word);
  }
  if(char==="}"||char==="^"||char==="_")throw new MathParseError("Invalid math expression.");
  this.index++;
  return {kind:"text",value:char};
 }
 private seq(terminator=""):Expr {
  const children:Expr[]=[];
  while(this.index<this.input.length && (!terminator||this.peek()!==terminator)){
   if(/\s/.test(this.peek())){this.index++;continue;}
   const char=this.peek();
   if(char==="^"||char==="_"){
    this.index++;
    const base=children.pop();
    if(!base)throw new MathParseError("Superscript has no base.");
    const script=this.atom();
    children.push({kind:"script",mode:char==="^"?"sup":"sub",base,script});
   }else children.push(this.atom());
  }
  return {kind:"row",children};
 }
 parse():Expr {const result=this.seq();if(this.index!==this.input.length)throw new MathParseError("Unparsed equation content.");return result;}
}
function draw(expr:Expr, key:string):ReactNode {
 switch(expr.kind){
  case "row":return <mrow key={key}>{expr.children.map((child,i)=>draw(child,key+"-"+i))}</mrow>;
  case "text":return /[A-Za-zα-ωΑ-Ω]/.test(expr.value)?<mi key={key}>{expr.value}</mi>: /[0-9]/.test(expr.value)?<mn key={key}>{expr.value}</mn>:<mo key={key}>{expr.value}</mo>;
  case "fraction":return <mfrac key={key}>{draw(expr.numerator,key+"n")}{draw(expr.denominator,key+"d")}</mfrac>;
  case "radical":return <msqrt key={key}>{draw(expr.body,key+"r")}</msqrt>;
  case "script":return expr.mode==="sup"?<msup key={key}>{draw(expr.base,key+"b")}{draw(expr.script,key+"s")}</msup>:<msub key={key}>{draw(expr.base,key+"b")}{draw(expr.script,key+"s")}</msub>;
  case "matrix":return <mrow key={key}>{expr.brackets&&<mo>{expr.brackets[0]}</mo>}<mtable>{expr.rows.map((row,i)=><mtr key={i}>{row.map((cell,j)=><mtd key={j}>{draw(cell,key+"-"+i+"-"+j)}</mtd>)}</mtr>)}</mtable>{expr.brackets&&<mo>{expr.brackets[1]}</mo>}</mrow>;
 }
}
export function MathEquation({latex}:{latex:string}) {
 let expr:Expr;
 try {
  if(!latex||latex.length>5000)throw new MathParseError("Missing or oversized equation.");
  expr=new Parser(latex.trim().replace(/^\$/,"").replace(/\$$/,"")).parse();
 } catch(error){
  return <div role="alert" className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900"><p className="font-bold">Equation requires manual review</p><code className="break-all">{latex}</code><p className="mt-1">{error instanceof Error?error.message:"Unsupported equation syntax"}</p></div>;
 }
 return <div className="overflow-x-auto rounded-xl bg-slate-50 p-4"><math display="block" aria-label={"Equation: "+latex}>{draw(expr,"root")}</math><p className="mt-2 text-xs text-slate-500">Editable LaTeX • native MathML preview</p></div>;
}
