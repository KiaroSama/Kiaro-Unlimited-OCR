import { invoke, type DocumentInfo } from './bridge.js';
export interface Block {label:string; text:string; boxes:{x:number;y:number;width:number;height:number}[]}
export interface ReaderPage {page:number;text:string;blocks:Block[];complete?:boolean}
let generation=0;
let observer:IntersectionObserver|null=null;
let pending=Promise.resolve();
export const loadPages=(info:DocumentInfo)=>{
  const version=++generation;
  observer?.disconnect();
  const stage=document.getElementById('paper-stage')!;
  stage.replaceChildren();
  observer=new IntersectionObserver(entries=>{
    for(const entry of entries){
      if(!entry.isIntersecting)continue;
      const card=entry.target as HTMLElement;
      observer?.unobserve(card);
      if(card.querySelector('img'))continue;
      pending=pending.then(async()=>{
        if(version!==generation)return;
        try{
          const value=await invoke<DocumentInfo>('preview_page',{page:Number(card.dataset.page)});
          if(version!==generation)return;
          const image=document.createElement('img'); image.src=value.image;image.alt=`Source page ${value.page}`;
          image.onload=()=>{card.style.aspectRatio=String(image.naturalWidth/image.naturalHeight);};
          card.prepend(image);
          const loaded=Array.from(stage.querySelectorAll('.source-page img'));
          let count=loaded.length;
          for(const old of loaded){
            if(count<=8)break;
            const parent=old.parentElement!;
            if(Math.abs(Number(parent.dataset.page)-Number(card.dataset.page))>3){old.remove();observer?.observe(parent);count--;}
          }
        }catch(error){card.title=String(error);}
      });
    }
  },{root:stage,rootMargin:'500px'});
  for(let page=1;page<=info.total;page++){
    const card=document.createElement('div');card.className='source-page';card.dataset.page=String(page);
    const boxes=document.createElement('div');boxes.className='layout-boxes';card.append(boxes);
    const label=document.createElement('span');label.className='page-label';label.textContent=String(page);card.append(label);
    if(page===info.page){const img=document.createElement('img');img.id='preview';img.src=info.image;img.alt=`Source page ${page}`;card.prepend(img);}
    stage.append(card);observer.observe(card);
  }
};
export const showPage=(page:number)=>document.querySelector(`.source-page[data-page="${page}"]`)?.scrollIntoView({block:'start'});
export const updateBoxes=(pages:ReaderPage[])=>{
  for(const page of pages){
    const target=document.querySelector(`.source-page[data-page="${page.page}"] .layout-boxes`);
    if(!target)continue;
    const nodes:HTMLElement[]=[];
    for(const [index,block] of (page.blocks||[]).entries())for(const box of block.boxes||[]){
      if(![box.x,box.y,box.width,box.height].every(Number.isFinite))continue;
      const rect=document.createElement('div');rect.className='layout-box'+(!page.complete&&index===page.blocks.length-1?' current':'');
      rect.style.cssText=`left:${box.x*100}%;top:${box.y*100}%;width:${box.width*100}%;height:${box.height*100}%`;
      rect.title=block.label;nodes.push(rect);
    }
    target.replaceChildren(...nodes);
  }
};
