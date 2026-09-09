"""Render a local PNG architecture diagram; README needs no Mermaid support."""
from pathlib import Path
from html import escape
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]

def render():
    nodes=[(45,100,'教师管理页面','仅教师机本机访问'),(45,250,'学生浏览器','局域网 · 无需安装'),(360,170,'教师机应用','Flask / Waitress'),(680,70,'班级与学生','届数、学期、职务、私密备注'),(680,210,'统一座位业务接口','当前座位、存档、设备配置'),(680,350,'每节课堂与考勤','上下课、签到、换座审批'),(1030,70,'SQLite 数据库','各模块保存自己的记录'),(1030,210,'随机点名','范围、动画、学生端通知'),(1030,350,'班级数据与导出','课堂日志、CSV、原模板 Excel')]
    svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1380" height="560" viewBox="0 0 1380 560"><defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#7b929e"/></marker></defs><rect width="1380" height="560" fill="#f3f7f9"/><g font-family="Microsoft YaHei,Arial,sans-serif"><text x="45" y="48" font-size="26" fill="#304b58">工作方式与技术架构</text>']
    for points in ('305,140 332,140 332,210 360,210','305,290 332,290 332,210 360,210','620,210 650,210 650,110 680,110','620,210 650,210 650,250 680,250','620,210 650,210 650,390 680,390','940,110 1030,110','940,250 1030,250','940,390 1030,390','810,290 810,350','940,390 990,390 990,250 1030,250'):
        svg.append('<polyline points="'+points+'" fill="none" stroke="#7b929e" stroke-width="2" marker-end="url(#arrow)"/>')
    for x,y,title,sub in nodes:
        svg.append(f'<rect x="{x}" y="{y}" width="260" height="80" rx="12" fill="white" stroke="#b9d2d3"/><text x="{x+130}" y="{y+32}" text-anchor="middle" font-size="20" fill="#365d61">{escape(title)}</text><text x="{x+130}" y="{y+59}" text-anchor="middle" font-size="15" fill="#647d88">{escape(sub)}</text>')
    svg.append('<text x="45" y="492" font-size="18" fill="#365d61">单程序 · 单数据库 · 模块各自维护数据 · 学生端资源全部本地提供</text><text x="45" y="527" font-size="16" fill="#647d88">后续教学模块通过 lesson_id + student_id 关联课堂；不通过 Excel 交换数据。</text></g></svg>')
    path=ROOT/'docs/images/architecture.svg';path.write_text(''.join(svg),encoding='utf-8')
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':1380,'height':560},device_scale_factor=1)
        page.goto(path.as_uri());page.screenshot(path=str(path.with_suffix('.png')));browser.close()
if __name__=='__main__':render()
