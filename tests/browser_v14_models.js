async (page) => {
  const cards=page.locator('.model-test-card');
  if(await cards.count()!==6)throw new Error('Expected six distinct service/model cards including override');
  for(let i=0;i<6;i++){
    const card=cards.nth(i);
    for(const name of ['测试文本连接','测试图片生成','测试联网搜索']){
      await card.getByRole('button',{name,exact:true}).click();
      await page.getByRole('button',{name:'保存设置',exact:true}).waitFor({state:'visible'});
      await page.waitForFunction(()=>!document.querySelector('.modal-footer button.primary')?.disabled);
    }
    if(await card.locator('.tag').filter({hasText:'已通过'}).count()!==3)throw new Error('Capability result missing for card '+i);
    if(!await card.locator('img.connection-preview').isVisible())throw new Error('Missing image preview');
  }
  await page.locator('.settings-content').evaluate(el=>el.scrollTop=0);
  for(const [width,height] of [[1366,768],[1280,800]]){
    await page.setViewportSize({width,height});
    const overflow=await page.evaluate(()=>[document.documentElement,...document.querySelectorAll('.settings-content,.model-test-card')].some(el=>el.scrollWidth>el.clientWidth+2));
    if(overflow)throw new Error('Horizontal overflow at '+width);
    await page.screenshot({path:'output/diagnostics/screenshots/model-cards-'+width+'.png'});
  }
  if(await page.getByText('测试工作台搜索',{exact:true}).count())throw new Error('Legacy workbench test still visible');
  await page.getByRole('button',{name:'流程偏好',exact:true}).click();
  await page.getByLabel('联网模型',{exact:true}).waitFor();
  if(await page.getByLabel('优先搜索方式',{exact:true}).count())throw new Error('Old strategy selector remains');
  await page.screenshot({path:'output/diagnostics/screenshots/search-preferences.png'});
  await page.getByRole('button',{name:'关闭',exact:true}).click();
  return {cards:6,capabilityTests:18,sizes:[1366,1280],simulated:true};
}
