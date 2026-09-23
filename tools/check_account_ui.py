"""Account controls exercised inside the complete offline writing acceptance."""
import asyncio
from playwright.async_api import expect


async def before_generation(page, base):
    await page.get_by_role('button',name='账号与学习',exact=True).click()
    dialog=page.get_by_role('dialog',name='账号与学习',exact=True)
    await dialog.get_by_label('账号受众',exact=True).fill('忙碌的普通读者')
    await dialog.get_by_label('表达方式',exact=True).fill('自然展开，保留问题主线')
    await dialog.get_by_role('button',name='范文',exact=True).click()
    await dialog.get_by_label('范文名称',exact=True).fill('节奏参考')
    await dialog.get_by_label('粘贴范文正文',exact=True).fill('我在火星见过王博士。他送给我99颗宝石。\n\n这些私人经历仅存在于这份模拟范文。')
    await dialog.get_by_role('button',name='分析范文表达',exact=True).click()
    item=dialog.locator('details.service-card').filter(has=page.locator('summary',has_text='节奏参考'))
    await expect(item).to_contain_text('待确认')
    await item.locator('summary').first.click()
    await item.get_by_role('button',name='确认使用此表达参考',exact=True).click()
    await expect(item).to_contain_text('已确认')
    await page.screenshot(path='output/playwright/reliability/account-example.png',full_page=True)
    await dialog.get_by_role('button',name='关闭',exact=True).click()
    value=await (await page.request.get(base+'/api/account')).json()
    assert value['profile']['audience']=='忙碌的普通读者'
    assert value['profile']['expression']=='自然展开，保留问题主线'


async def after_generation(page, base, article_id, out):
    async def article():return await (await page.request.get(base+'/api/articles/'+article_id)).json()
    # The human change is made in the actual editor before explicitly finalizing.
    await page.get_by_role('button',name='Markdown 源文',exact=True).click()
    original=(await article())['content']
    await page.get_by_label('Markdown 正文',exact=True).fill(original+'\n\n不妨先想想，你真正想回答读者的哪个问题？')
    await page.get_by_role('button',name='记录人工定稿',exact=True).click()
    for _ in range(100):
        current=await article()
        if current['draft_versions'][-1].get('human_edit_base'):break
        await asyncio.sleep(.05)
    assert current['draft_versions'][-1]['human_edit_base']
    await page.get_by_role('button',name='账号与学习',exact=True).click()
    dialog=page.get_by_role('dialog',name='账号与学习',exact=True)
    await dialog.get_by_role('button',name='人工改稿学习',exact=True).click()
    await dialog.get_by_role('button',name='分析这一人工改稿对',exact=True).click()
    await expect(dialog.get_by_role('button',name='此改稿对已学习',exact=True)).to_be_visible()
    await expect(dialog.get_by_label('偏好内容',exact=True)).to_have_value('长短段落交替，结尾留给读者一个具体问题')
    await dialog.get_by_role('button',name='确认固定此偏好',exact=True).click()
    await dialog.get_by_role('button',name='明确扩大到全账号',exact=True).click()
    await expect(dialog).to_contain_text('全账号')
    await dialog.get_by_label('偏好内容',exact=True).fill('段落长短自然变化')
    await dialog.get_by_label('偏好内容',exact=True).press('Tab')
    await expect(dialog).to_contain_text('软参考')
    await dialog.get_by_role('button',name='停用',exact=True).click()
    await expect(dialog).to_contain_text('已停用')
    await dialog.get_by_role('button',name='重新启用为软参考',exact=True).click()
    await dialog.get_by_role('button',name='撤销使用',exact=True).click()
    await expect(dialog).to_contain_text('已撤销')
    await dialog.get_by_role('button',name='删除',exact=True).click()
    await expect(dialog.get_by_label('偏好内容',exact=True)).to_have_count(0)
    await dialog.get_by_role('button',name='撤销上次账号修改',exact=True).click()
    await expect(dialog).to_contain_text('已撤销')
    await dialog.get_by_role('button',name='重新启用为软参考',exact=True).click()
    await dialog.get_by_role('button',name='历史索引',exact=True).click()
    row=dialog.locator('details.service-card').filter(has=page.locator('summary',has_text=current['title']))
    await row.locator('summary').first.click()
    await row.get_by_role('button',name='编辑索引',exact=True).click()
    edit=page.get_by_role('dialog',name='编辑历史索引',exact=True)
    await edit.get_by_label('历史角度',exact=True).fill('同主题的新证据')
    await edit.get_by_role('button',name='保存历史索引',exact=True).click()
    await expect(edit).to_have_count(0)
    await expect(row).to_contain_text('同主题的新证据')
    await dialog.get_by_role('button',name='效果记录',exact=True).click()
    await dialog.get_by_label('发布时间',exact=True).fill('2025-01-01T08:00')
    await dialog.get_by_label('统计时间',exact=True).fill('2025-01-02T08:00')
    await dialog.get_by_label('阅读',exact=True).fill('100')
    await dialog.get_by_role('button',name='保存效果记录',exact=True).click()
    await expect(dialog).to_contain_text('可比较的已知指标不足五篇')
    metric=dialog.locator('details.service-card').last
    await metric.locator('summary').first.click()
    await expect(metric).to_contain_text('点赞：未知')
    # Bad CSV is one failed task; no row is partially committed.
    csv='article_id,published_at,observed_at,reads\n'+article_id+',2025-02-01,2025-02-02,20\nmissing,2025-02-01,2025-02-02,20\n'
    await dialog.locator('input[type=file]').set_input_files({'name':'bad.csv','mimeType':'text/csv','buffer':csv.encode()})
    await expect(dialog).to_contain_text('找不到这篇文章')
    value=await (await page.request.get(base+'/api/account')).json();assert len(value['metrics'])==1
    await dialog.get_by_role('button',name='本篇使用记录',exact=True).click()
    uses=await (await page.request.get(base+'/api/articles/'+article_id+'/account-uses')).json()
    assert {'topic','outline','write','edit'}<={u['stage'] for u in uses['uses']}
    for u in uses['uses']:
        assert u['context']['profile']['audience']=='忙碌的普通读者'
        assert u['context']['examples'] and 'text' not in u['context']['examples'][0]
    first=dialog.locator('details.service-card').first
    await first.locator('summary').first.click()
    await expect(first).to_contain_text('忙碌的普通读者')
    for width in (1440,1100,390):
        await page.set_viewport_size({'width':width,'height':900})
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
        assert await dialog.evaluate('(el)=>el.scrollWidth<=el.clientWidth'),width
        await page.screenshot(path=str(out/f'account-{width}.png'),full_page=True)
    await page.set_viewport_size({'width':1440,'height':1000})
    await dialog.get_by_role('button',name='关闭',exact=True).click()
    # Make an actual subsequent call to verify the learned rule enters editing.
    await page.get_by_role('button',name='生成整体编辑候选',exact=True).click()
    candidate=page.locator('.editorial-candidate').first
    await expect(candidate.locator('summary').first).to_contain_text('已完成复审')
    uses=await (await page.request.get(base+'/api/articles/'+article_id+'/account-uses')).json()
    assert uses['uses'][0]['context']['rules'][0]['text']=='段落长短自然变化'
    assert (await article())['content']==current['content']
