async (page) => {
  await page.getByRole('button',{name:/排版导出/}).first().click();
  await page.getByRole('combobox',{name:'排版主题',exact:true}).selectOption('sspai');
  await page.getByRole('textbox',{name:'署名',exact:true}).fill('WeWrite 界面验收');
  await page.getByRole('textbox',{name:'署名',exact:true}).press('Tab');
  await page.getByRole('button',{name:'更新排版',exact:true}).click();
  await page.getByRole('button',{name:'更新排版',exact:true}).waitFor({state:'visible'});
  const download=page.waitForEvent('download');
  await page.getByRole('link',{name:'下载完整文章包',exact:true}).click();
  const result=await download;await result.saveAs('output/diagnostics/screenshots/验收文章.zip');
  await page.context().grantPermissions(['clipboard-read','clipboard-write']);
  await page.getByRole('button',{name:'复制公众号排版',exact:true}).click();
  await page.getByRole('button',{name:'已复制',exact:true}).waitFor();
  const clipboard=await page.evaluate(async()=>await navigator.clipboard.readText());
  if(!clipboard.includes('人工补充'))throw new Error('clipboard lost content');
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:'output/diagnostics/screenshots/layout.png',fullPage:false});
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth);
  if(overflow)throw new Error('desktop horizontal overflow');
  return {export:result.suggestedFilename(),clipboard:true,overflow:false};
}
