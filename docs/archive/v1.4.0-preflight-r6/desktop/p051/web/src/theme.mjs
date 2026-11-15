import tokens from './design-tokens.json';
export const colors=tokens;
export function applyTheme(document){
  for(const [name,value] of Object.entries(tokens)){
    if(typeof value==='string')document.documentElement.style.setProperty('--'+name,value);
  }
}
