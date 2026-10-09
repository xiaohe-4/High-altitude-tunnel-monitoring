# -*- coding: utf-8 -*-
"""按附件2版式生成作品 PPT。"""

from __future__ import annotations

import shutil
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

ROOT = Path(r"C:\Users\yumen\Desktop\移动杯")
TEMPLATE = ROOT / "附件2：作品PPT模板.pptx"
OUTPUT = ROOT / "高海拔隧道智能监测预警Agent.pptx"

A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
GRADIENT = (
    f'<a:gradFill xmlns:a="{A_NS}">'
    '<a:gsLst>'
    '<a:gs pos="0"><a:srgbClr val="FFFFFF"/></a:gs>'
    '<a:gs pos="100000"><a:srgbClr val="92BAFF"/></a:gs>'
    "</a:gsLst>"
    '<a:lin ang="0" scaled="0"/>'
    "</a:gradFill>"
)

SLIDE_W = 13.333
SLIDE_H = 7.5


def rgb(value: str) -> RGBColor:
    return RGBColor.from_string(value)


def set_run_font(run, size: float, bold=False, color: str | None = None, italic=False, gradient=False):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.name = "微软雅黑"
    r_pr = run._r.get_or_add_rPr()
    for tag in ("a:latin", "a:ea", "a:cs"):
        node = r_pr.find(qn(tag))
        if node is None:
            node = etree.SubElement(r_pr, qn(tag))
        node.set("typeface", "微软雅黑")
    for child in list(r_pr):
        if child.tag in (qn("a:solidFill"), qn("a:gradFill")):
            r_pr.remove(child)
    if gradient:
        r_pr.append(etree.fromstring(GRADIENT))
    elif color:
        run.font.color.rgb = rgb(color)


def write_lines(shape, lines, size, bold=False, color="FFFFFF", align="left", gradient=False, italic=False, anchor="top", spacing=4):
    frame = shape.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.auto_size = None
    anchor_map = {"top": MSO_ANCHOR.TOP, "middle": MSO_ANCHOR.MIDDLE, "bottom": MSO_ANCHOR.BOTTOM}
    frame.paragraphs[0].alignment = PP_ALIGN.LEFT
    try:
        frame._txBody.bodyPr.set("anchor", {"top": "t", "middle": "ctr", "bottom": "b"}[anchor])
    except Exception:
        pass
    align_map = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}
    for index, line in enumerate(lines):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.alignment = align_map[align]
        paragraph.space_after = Pt(spacing if index < len(lines) - 1 else 0)
        paragraph.space_before = Pt(0)
        paragraph.line_spacing = 1.05
        run = paragraph.add_run()
        run.text = line
        set_run_font(run, size, bold=bold, color=color, italic=italic, gradient=gradient)
    frame.margin_left = Emu(0)
    frame.margin_right = Emu(0)
    frame.margin_top = Emu(0)
    frame.margin_bottom = Emu(0)
    return frame


def add_text(slide, x, y, w, h, lines, size, bold=False, color="FFFFFF", align="left", gradient=False, italic=False, anchor="top", spacing=3):
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    write_lines(shape, lines, size, bold, color, align, gradient, italic, anchor, spacing)
    return shape


def fill_shape(shape, color: str, alpha: int | None = None, line: str | None = "3E6FBF", line_pt=1.0):
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(color)
    solid = shape._element.spPr.find(qn("a:solidFill"))
    srgb = solid.find(qn("a:srgbClr"))
    if alpha is not None and srgb is not None:
        alpha_node = etree.SubElement(srgb, qn("a:alpha"))
        alpha_node.set("val", str(alpha))
    if line:
        shape.line.color.rgb = rgb(line)
        shape.line.width = Pt(line_pt)
    else:
        shape.line.fill.background()
    return shape


def add_round(slide, x, y, w, h, fill="10284F", alpha=90000, line="4C7ED6", line_pt=1.0, radius=0.12):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    try:
        shape.adjustments[0] = radius
    except Exception:
        pass
    fill_shape(shape, fill, alpha, line, line_pt)
    shape.shadow.inherit = False
    return shape


def add_card(slide, x, y, w, h, kicker, title, body, kicker_color="8EB6FF"):
    add_round(slide, x, y, w, h)
    pad_x = 0.18
    add_text(slide, x + pad_x, y + 0.14, w - pad_x * 2, 0.28, [kicker], 12, True, kicker_color)
    add_text(slide, x + pad_x, y + 0.42, w - pad_x * 2, 0.38, [title], 18, True, "FFFFFF")
    add_text(slide, x + pad_x, y + 0.86, w - pad_x * 2, h - 1.02, body if isinstance(body, list) else [body], 14, False, "D5E3FA", spacing=2)
    return


def add_lead(slide, text):
    add_text(slide, 0.68, 1.38, 12.0, 0.42, [text], 15, False, "C5D6F5", anchor="middle")


def content_title(slide, title):
    placeholder = slide.placeholders[10]
    placeholder.left = Inches(2.3)
    placeholder.top = Inches(0.68)
    placeholder.width = Inches(8.7)
    placeholder.height = Inches(0.62)
    write_lines(placeholder, [title], 26, bold=True, color="FFFFFF", align="center", anchor="middle")


def new_content(prs, title, note):
    slide = prs.slides.add_slide(prs.slide_layouts[3])
    content_title(slide, title)
    slide.notes_slide.notes_text_frame.text = note
    return slide


def new_section(prs, part, title, note):
    slide = prs.slides.add_slide(prs.slide_layouts[2])
    add_text(
        slide,
        3.36,
        2.22,
        6.62,
        0.72,
        [part],
        32,
        bold=True,
        align="center",
        gradient=True,
        italic=True,
        anchor="middle",
    )
    bar = add_round(slide, 5.55, 3.02, 2.24, 0.055, fill="92BAFF", alpha=None, line=None, radius=0.5)
    bar.line.fill.background()
    placeholder = slide.placeholders[10]
    write_lines(placeholder, [title], 40, bold=True, align="center", gradient=True, anchor="middle")
    slide.notes_slide.notes_text_frame.text = note
    return slide


def delete_slide(prs, index):
    slide_id_list = prs.slides._sldIdLst
    slide_id = slide_id_list[index]
    rel_id = slide_id.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
    prs.part.drop_rel(rel_id)
    slide_id_list.remove(slide_id)


def renumber_slides(prs):
    slide_id_list = prs.slides._sldIdLst
    prs.part.rename_slide_parts([slide_id.rId for slide_id in slide_id_list])


def move_to_end(prs, index):
    slide_id_list = prs.slides._sldIdLst
    element = slide_id_list[index]
    slide_id_list.remove(element)
    slide_id_list.append(element)


def build_cover(slide):
    placeholder = slide.placeholders[10]
    write_lines(
        placeholder,
        ["高海拔隧道监测预警", "MoMA 智能 Agent"],
        32,
        bold=True,
        align="left",
        gradient=True,
        anchor="middle",
        spacing=8,
    )
    for shape in slide.shapes:
        if shape.has_text_frame and "演讲人" in shape.text_frame.text:
            shape.text_frame.paragraphs[0].runs[0].text = "演讲人：项目组"
    add_text(slide, 0.91, 4.28, 6.4, 0.36, ["平台适配与应用 · 色尔岗曲隧道"], 16, False, "D5E3FA")


def build_toc(slide):
    titles = ["Agent 简介", "平台适配", "平台应用", "效果与价值"]
    indexes = [10, 13, 14, 15]
    for idx, title in zip(indexes, titles):
        placeholder = slide.placeholders[idx]
        write_lines(placeholder, [title], 26, bold=True, color="FFFFFF", align="left", anchor="middle")
    slide.notes_slide.notes_text_frame.text = "中间两章是重点：平台能力怎么适配到隧道任务，以及这些能力在值守台上怎么用。"


def slide_problem(prs):
    slide = new_content(
        prs,
        "问题在哪里",
        "先讲真实值班场景：视频、气体、设备日志是三套东西，人眼来回切换。再点名色尔岗曲隧道右线三个视频点位。",
    )
    add_lead(slide, "值守要同时看视频、洞内环境和设备日志。异常分散，漏报和误报的代价都不一样。")
    cards = [
        ("01", "看不过来", ["入口、中段、出口共三路视频。", "同时要看一氧化碳、光照、风速、能见度和设备日志。"]),
        ("02", "边界难判", ["停车、缓行和短停容易混在一起。", "环境起伏有时只是通风或照明切换。"]),
        ("03", "代价不对称", ["停驶和一氧化碳升高关系洞内安全。", "误报太密，值班席会逐渐不看系统。"]),
    ]
    for index, (kicker, title, body) in enumerate(cards):
        add_card(slide, 0.68 + index * 4.15, 2.05, 3.95, 2.85, kicker, title, body)
    add_text(
        slide,
        0.68,
        5.2,
        12.0,
        0.85,
        ["场景锚定在久马高速色尔岗曲隧道右线，海拔 3000 米以上。", "视频点位为 K920+765、K922+065、K924+165，环境与设备记录按该隧道筛选。"],
        15,
        False,
        "E7F0FF",
        spacing=4,
    )


def slide_users(prs):
    slide = new_content(
        prs,
        "谁在使用",
        "三个用户要的东西不一样：值班员要一句能执行的话，运维要关联，管理人员要留档。",
    )
    add_lead(slide, "使用者是隧道运营侧的值班员、运维工程师和管理人员。")
    cards = [
        ("值守员", "要不要上报", "需要一句能执行的话：疑似真实、证据不足，还是不像异常，以及是否建议人工上报。"),
        ("运维工程师", "放在一起看", "把同一时段的视频目标、环境读数和设备故障放在一处，再决定要不要继续查。"),
        ("管理单位", "能复核、能留档", "保留结论、证据指向和人工建议。模型名称、Token 和耗时一并回显。"),
    ]
    for index, (title, kicker, body) in enumerate(cards):
        add_card(slide, 0.68 + index * 4.15, 2.05, 3.95, 3.15, kicker, title, body, "F0A05A" if index == 0 else "8EB6FF")


def slide_scope(prs):
    slide = new_content(
        prs,
        "交付什么",
        "强调 Agent 的交付物是可复核的短结论。现场数据和演示数据分开。原始视频不上传。",
    )
    add_lead(slide, "Agent 负责先筛再判，把能核对的证据收成短结论，处置仍由人工确认。")
    add_round(slide, 0.68, 2.05, 6.0, 4.4)
    add_round(slide, 6.88, 2.05, 5.8, 4.4)
    add_text(slide, 0.9, 2.22, 5.5, 0.4, ["当前会交付"], 18, True, "7ED0A0")
    add_text(
        slide,
        0.9,
        2.75,
        5.5,
        3.4,
        [
            "现场一氧化碳和光照先核对，落在已有记录范围内就不进入异常。",
            "检出异常后才调用 MoMA，返回判定和上报建议。",
            "模拟事件带“模拟”标记，与现场结论分开展示。",
            "停驶复用本机 YOLOv8n 结果，原始视频留在本地。",
        ],
        15,
        False,
        "E7F0FF",
        spacing=10,
    )
    add_text(slide, 7.1, 2.22, 5.4, 0.4, ["使用时需要知道"], 18, True, "F0A05A")
    add_text(
        slide,
        7.1,
        2.75,
        5.3,
        3.4,
        [
            "环境表是 2026 年 6 月的历史参考，不代表当前实时流。",
            "现场表没有温度序列，温度条目是演示假设。",
            "结论供人工确认后再处置。",
            "图像输入、工作流和 RAG 仍待官方接口确认。",
        ],
        15,
        False,
        "E7F0FF",
        spacing=10,
    )


def slide_fit(prs):
    slide = new_content(
        prs,
        "适配对照",
        "这是重点页。从左到右讲：MoMA 提供什么，本项目就改哪一处接入，不讲自建模型。",
    )
    add_lead(slide, "隧道侧不自建大模型。任务改接到 MoMA 已经提供的路由、上下文和可观测能力上。")
    rows = [
        ("一次接入", "只提交已确认的聊天补全字段。具体模型以平台返回为准。"),
        ("三档策略", "成本、均衡、效果对应不同温度、top_p 和输出长度。"),
        ("上下文复用", "追问沿用第一次数据快照，过长时只留系统提示和最近几轮。"),
        ("失败隔离", "单类等待上限 45 秒。一类没有结论，其余类型继续。"),
        ("按需调用", "没有异常不调用。相同异常走缓存。Token 按策略封顶。"),
    ]
    add_round(slide, 0.68, 1.95, 3.35, 0.5, fill="1B4F9C", alpha=None, line=None, radius=0.12)
    add_round(slide, 4.15, 1.95, 8.5, 0.5, fill="1B4F9C", alpha=None, line=None, radius=0.12)
    add_text(slide, 0.86, 2.05, 3.0, 0.32, ["平台能力"], 15, True, "FFFFFF", anchor="middle")
    add_text(slide, 4.35, 2.05, 8.1, 0.32, ["本项目怎么适配"], 15, True, "FFFFFF", anchor="middle")
    for index, (left, right) in enumerate(rows):
        top = 2.56 + index * 0.82
        add_round(slide, 0.68, top, 3.35, 0.72, fill="14356F", alpha=None, line="3E6FBF", radius=0.12)
        add_round(slide, 4.15, top, 8.5, 0.72, radius=0.12)
        add_text(slide, 0.86, top + 0.16, 3.0, 0.4, [left], 16, True, "8EB6FF", anchor="middle")
        add_text(slide, 4.35, top + 0.16, 8.1, 0.4, [right], 15, False, "E7F0FF", anchor="middle")


def slide_apply(prs):
    slide = new_content(
        prs,
        "应用闭环",
        "这是重点页。用一次值班把平台能力串起来：何时调用、选哪档、返回什么、人如何接着问。",
    )
    add_lead(slide, "MoMA 用在需要判断的那几步。正常记录不进平台，异常才变成可复核的上报建议。")
    items = [
        ("01", "何时调用", "本地先核对现场记录和停驶。没有异常就不调用平台。"),
        ("02", "选哪一档", "照度、温度走成本优先。一氧化碳走均衡优先。停驶和画面目标走效果优先。"),
        ("03", "平台返回", "两句结论：像不像异常，要不要上报。路由表回显模型名、Token 和耗时。"),
        ("04", "人接着用", "追问复用第一次快照。两类以上只拿短结论做关联。全无结论时走离线备用。"),
    ]
    for index, (num, title, body) in enumerate(items):
        col, row = index % 2, index // 2
        add_card(slide, 0.68 + col * 6.3, 1.98 + row * 2.35, 6.1, 2.2, num, title, body, "F0A05A" if index == 0 else "8EB6FF")


def slide_abilities(prs):
    slide = new_content(
        prs,
        "能力一览",
        "六项能力和页面一一对应：核对、停驶、分流、关联、追问、离线兜底。",
    )
    add_lead(slide, "每项能力都先回答两个平台问题：要不要调用 MoMA，以及走哪一档路由。")
    items = [
        ("01", "现场核对", "读取色尔岗曲隧道的一氧化碳和光照历史，范围之内不作为本次异常。"),
        ("02", "停驶初判", "用播放器同一份 YOLOv8n 结果判断车辆是否基本不动，不另做一次推理。"),
        ("03", "策略分流", "照度和温度走成本优先，一氧化碳走均衡优先，停驶和画面目标走效果优先。"),
        ("04", "多源关联", "两类及以上异常时，只用各类短结论再做一次均衡关联。"),
        ("05", "多轮追问", "同一会话复用第一次提交的数据快照，避免把传感器记录重复发送。"),
        ("06", "离线兜底", "云端都没有可见结论时，展示事先写好的备用结论，并标明来源。"),
    ]
    for index, item in enumerate(items):
        col, row = index % 3, index // 3
        add_card(slide, 0.62 + col * 4.2, 1.95 + row * 2.4, 4.02, 2.25, item[0], item[1], item[2])


def slide_models(prs):
    slide = new_content(
        prs,
        "模型调度",
        "讲清楚已经接入的是 MoMA 智能路由，三种策略映射到温度、top_p 和输出长度。模型名以平台返回为准。方案里的 DeepSeek、千问、GLM、九天、Kimi 是任务对应关系，请求里不写死未确认参数。",
    )
    add_lead(slide, "一次接入移动云 MoMA 智能路由。策略由应用选择，实际模型名称以平台返回为准。")
    strategies = [
        ("成本优先", "温度 0.1 · top_p 0.8", "回答短。巡检摘要，以及照度、温度一类简单形态，走这条链路。", "8EB6FF"),
        ("均衡优先", "温度 0.2 · top_p 0.9", "兼顾证据和篇幅。一氧化碳复核、多源关联走这条链路。", "7ED0A0"),
        ("效果优先", "温度 0.3 · top_p 0.95", "把能核对的证据写清楚。车辆停驶和画面目标走这条链路。", "F0A05A"),
    ]
    for index, (name, params, body, color) in enumerate(strategies):
        add_card(slide, 0.68 + index * 4.15, 1.95, 3.95, 2.45, params, name, body, color)
    add_round(slide, 0.68, 4.65, 12.0, 1.28, fill="0E2248", alpha=92000)
    add_text(
        slide,
        0.9,
        4.88,
        11.6,
        0.95,
        [
            "方案中的任务对应：轨迹推理面向 DeepSeek 一类推理模型，图像精判面向九天多模态或千问多模态，",
            "多源分级面向 GLM 长上下文，巡检文本面向 DeepSeek、Kimi。当前请求只提交已确认字段，页面回显模型名、Token 和耗时。",
        ],
        14,
        False,
        "D5E3FA",
        spacing=4,
    )


def slide_routing(prs):
    slide = new_content(
        prs,
        "分流规则",
        "这是能力设计的核心表。强调多源关联不重复上传原始表和视频。单类等待上限 45 秒。",
    )
    add_lead(slide, "异常按类型组包。没有异常不调用；同一异常命中缓存后不再重复提交。")
    header = ["对象", "策略", "调用方式"]
    rows = [
        ["照度、温度", "成本优先", "输出更短，保留结论、一条证据和一条人工建议"],
        ["一氧化碳", "均衡优先", "对照该测点历史范围；信息不足时写明无法判定风险等级"],
        ["车辆停驶、画面目标", "效果优先", "写清能核对的证据，并区分演示注入和现场记录"],
        ["两类及以上", "均衡 · 多源关联", "只汇总各类短结论，判断是否合并上报"],
    ]
    widths = [3.15, 2.55, 6.05]
    x0, y = 0.68, 1.98
    xs = [x0]
    for width in widths[:-1]:
        xs.append(xs[-1] + width + 0.12)
    for x, width, text in zip(xs, widths, header):
        add_round(slide, x, y, width, 0.48, fill="1B4F9C", alpha=None, line=None, radius=0.15)
        add_text(slide, x + 0.16, y + 0.08, width - 0.28, 0.32, [text], 14, True, "FFFFFF", anchor="middle")
    for row_index, row in enumerate(rows):
        top = 2.58 + row_index * 1.02
        for x, width, text in zip(xs, widths, row):
            add_round(slide, x, top, width, 0.92, fill="10284F", alpha=90000, radius=0.12)
            add_text(slide, x + 0.16, top + 0.16, width - 0.3, 0.62, [text], 14, False, "E7F0FF", anchor="middle")


def slide_levels(prs):
    slide = new_content(
        prs,
        "分级提示",
        "L0 到 L3 是方案中的提示等级。原型当前先输出是否建议人工上报。方案演示区的等级样例要和现场曲线分开讲。",
    )
    add_lead(slide, "风险提示按打扰程度分级。等级越高，通知越靠前，证据要求也越完整。")
    levels = [
        ("L0", "正常留痕", "只记录状态，不推送。", "8EB6FF"),
        ("L1", "巡检留档", "写入当班巡检摘要。", "7ED0A0"),
        ("L2", "值守复核", "推送到值守端，建议人工看证据。", "F2BA02"),
        ("L3", "立即通知", "值守端与值班通知一起发。", "E54C5E"),
    ]
    for index, (level, title, body, color) in enumerate(levels):
        x = 0.68 + index * 3.15
        add_round(slide, x, 2.05, 3.0, 2.55)
        add_text(slide, x + 0.18, 2.22, 2.64, 0.55, [level], 28, True, color)
        add_text(slide, x + 0.18, 2.85, 2.64, 0.45, [title], 18, True, "FFFFFF")
        add_text(slide, x + 0.18, 3.4, 2.64, 1.4, [body], 15, False, "D5E3FA")
    add_text(
        slide,
        0.68,
        4.9,
        12.0,
        1.05,
        [
            "当前原型先交付“是否建议人工上报”。页面上的 L0–L3 位于方案演示区，与现场曲线、模拟异常分开。",
            "规则冻结和连续回放完成之前，这些等级是设计口径，不作为现场告警成绩。",
        ],
        15,
        False,
        "E7F0FF",
        spacing=4,
    )


def _arch_box(slide, x, y, w, h, title, sub, live=True):
    add_round(slide, x, y, w, h, fill="102A52", alpha=94000, line="6FA2E8" if live else "C47A45", line_pt=1.25, radius=0.1)
    if sub:
        add_text(slide, x + 0.06, y + 0.05, w - 0.12, 0.28, [title], 12, True, "FFFFFF", align="center")
        add_text(slide, x + 0.04, y + 0.32, w - 0.08, h - 0.36, [sub], 10, False, "D5E3FA", align="center")
    else:
        add_text(slide, x + 0.04, y, w - 0.08, h, [title], 11, True, "FFFFFF", align="center", anchor="middle")


def _arch_row(slide, x, y, width, height, items, gap=0.1):
    count = len(items)
    box_w = (width - gap * (count - 1)) / count
    for index, item in enumerate(items):
        title, sub, live = item
        _arch_box(slide, x + index * (box_w + gap), y, box_w, height, title, sub, live)


def slide_architecture(prs):
    slide = new_content(
        prs,
        "项目架构",
        "按三层讲总图。绿框是当前已接入，橙框是方案中的任务对应。强调原始视频不上云，MoMA 只收结构化异常。",
    )
    add_text(
        slide,
        8.55,
        1.32,
        4.3,
        0.28,
        ["绿框 已接入    橙框 方案对应"],
        11,
        False,
        "C5D6F5",
        align="right",
        anchor="middle",
    )

    add_round(slide, 0.42, 1.58, 12.5, 1.18, fill="0C2044", alpha=88000, line="3E6FBF", radius=0.08)
    add_text(slide, 0.55, 1.66, 1.35, 0.28, ["应用输出"], 12, True, "7ED0A0")
    _arch_row(
        slide,
        1.95,
        1.68,
        10.8,
        0.92,
        [
            ("值守台", "Web 监测席", True),
            ("曲线与视频", "现场记录与回看", True),
            ("路由回显", "模型·Token·耗时", True),
            ("多轮追问", "复用会话快照", True),
            ("分级复核", "L0–L3·人工确认", False),
        ],
    )

    add_text(slide, 0.42, 2.78, 12.5, 0.24, ["↑  短结论、证据指向、追问"], 11, False, "8EB6FF", align="center")

    add_round(slide, 0.42, 3.04, 12.5, 2.42, fill="0E2C5C", alpha=90000, line="8EB6FF", line_pt=1.5, radius=0.08)
    add_text(slide, 0.55, 3.1, 4.2, 0.26, ["MoMA 核心"], 12, True, "8EB6FF")
    add_text(slide, 0.55, 3.4, 1.15, 0.7, ["已接入"], 11, True, "7ED0A0", anchor="middle")
    _arch_row(
        slide,
        1.75,
        3.4,
        10.95,
        0.7,
        [
            ("智能路由", "一次接入", True),
            ("成本优先", "照度·温度", True),
            ("均衡优先", "一氧化碳·多源", True),
            ("效果优先", "停驶·画面", True),
        ],
    )
    add_text(slide, 0.55, 4.18, 1.15, 0.7, ["任务对应"], 11, True, "F0A05A", anchor="middle")
    _arch_row(
        slide,
        1.75,
        4.18,
        10.95,
        0.72,
        [
            ("数据融合", "五级时空索引", False),
            ("轨迹分析", "DeepSeek-R1", False),
            ("视觉精判", "九天·千问", False),
            ("环境分析", "时序·DeepSeek", False),
            ("设备状态", "Kimi·DeepSeek", False),
            ("统一分级", "GLM-5.2", False),
        ],
    )
    _arch_row(
        slide,
        0.58,
        5.0,
        12.18,
        0.36,
        [
            ("报告 · DeepSeek-V3", "", False),
            ("交互追问", "", True),
            ("RAG 待确认", "", False),
            ("上下文复用", "", True),
            ("失败隔离", "", True),
        ],
        gap=0.08,
    )

    add_text(slide, 0.42, 5.48, 12.5, 0.22, ["↑  MQTT / HTTPS    只上传异常结构化结果，原始视频留在本地"], 11, False, "F0A05A", align="center")

    add_round(slide, 0.42, 5.72, 12.5, 1.22, fill="0C2044", alpha=88000, line="C47A45", radius=0.08)
    add_text(slide, 0.55, 5.78, 1.35, 0.24, ["边缘感知"], 12, True, "F0A05A")
    _arch_row(
        slide,
        0.55,
        6.06,
        12.22,
        0.76,
        [
            ("三路枪机", "K920·K922·K924", False),
            ("YOLOv8n", "本地检测缓存", True),
            ("ByteTrack", "轨迹关联", False),
            ("环境记录", "CO·光照核对", True),
            ("设备日志", "故障与恢复", True),
            ("本地初判", "异常才上云", True),
        ],
    )


def slide_prompt(prs):
    slide = new_content(
        prs,
        "Prompt 策略",
        "四条策略：任务角色、两句话输出、数据约束、会话裁剪。举例说明模拟必须写明，同时出现不能说成因果。",
    )
    add_lead(slide, "Prompt 把模型限制在可核对的判断上，避免长文和越权结论。")
    items = [
        ("角色按任务换", "常规巡检只概括曲线和留档事项。异常复核指出起伏和未恢复故障。多源关联只看两类记录里能直接读到的关系。"),
        ("输出收成两句", "第一句给判定：疑似真实、证据不足或不像异常。第二句给是否建议人工上报。展示前去掉思考过程标签。"),
        ("数据约束写进提示", "带模拟标记的条目必须写明模拟。不要编造阈值。同时出现的记录不能直接说成因果关系。"),
        ("上下文只留有用的", "追问沿用第一次的数据快照。消息过长时保留系统提示、首条快照和最近几轮，避免重复粘贴整表。"),
    ]
    for index, (title, body) in enumerate(items):
        col, row = index % 2, index // 2
        add_card(slide, 0.68 + col * 6.3, 1.95 + row * 2.35, 6.1, 2.2, f"0{index + 1}", title, body)


def slide_tools(prs):
    slide = new_content(
        prs,
        "调用过程",
        "按五步讲工具链：本地筛查、分流、并行补全、多源关联、缓存和离线兜底。单类 45 秒。",
    )
    add_lead(slide, "工具不上传原始视频。聊天补全只接收筛查后的结构化异常，或各类已经生成的短结论。")
    steps = [
        ("1", "本地筛查", "传感器解析和停驶判定先在本机完成。"),
        ("2", "按类组包", "生成路由计划，写明策略、温度和 Token 上限。"),
        ("3", "并行补全", "每类单独请求。单类等待上限 45 秒。"),
        ("4", "短结论融合", "两类以上，才把短结论再关联一次。"),
        ("5", "缓存与兜底", "相同异常复用结论。全无结果时走离线备用。"),
    ]
    for index, (num, title, body) in enumerate(steps):
        x = 0.5 + index * 2.56
        add_round(slide, x, 2.05, 2.42, 2.85)
        add_text(slide, x + 0.14, 2.2, 2.14, 0.48, [num], 26, True, "8EB6FF", align="center")
        add_text(slide, x + 0.14, 2.72, 2.14, 0.4, [title], 16, True, "FFFFFF", align="center")
        add_text(slide, x + 0.14, 3.2, 2.14, 1.4, [body], 13, False, "D5E3FA", align="center")
    add_round(slide, 0.5, 5.1, 12.35, 1.4)
    add_text(
        slide,
        0.72,
        5.28,
        12.0,
        1.05,
        [
            "本机工具：环境表解析、YOLOv8n 检测缓存、停驶判定、路由计划、会话记忆、离线备用结论。",
            "云端工具：MoMA Chat Completions。人工分析可选常规巡检、异常复核、多源关联，并对应三种路由策略。",
        ],
        15,
        False,
        "E7F0FF",
        spacing=4,
    )


def slide_tests(prs):
    slide = new_content(
        prs,
        "测试表现",
        "只讲测试已经锁定的行为。不要把方案里的 mAP、F1 说成已经测出的分数。历史数据和演示片要主动说明。",
    )
    add_lead(slide, "测试盯住平台接法：策略有没有走对，Token 有没有按档封顶，一类失败会不会拖垮其余调用。")
    add_round(slide, 0.62, 1.95, 6.15, 4.55)
    add_round(slide, 6.95, 1.95, 5.75, 4.55)
    add_text(slide, 0.84, 2.1, 5.7, 0.38, ["已经核对"], 18, True, "7ED0A0")
    add_text(
        slide,
        0.84,
        2.58,
        5.7,
        3.7,
        [
            "现场一氧化碳和光照落在各测点已有范围内，本次不作为异常。",
            "车辆持续移动不判停驶；位置基本不动且持续时间达到门槛，才列为停驶候选。",
            "视频文件名被限制在视频目录内。",
            "异常链路 Token 上限：成本 512，均衡 640，效果 768。",
            "某一类没有形成结论时，其余类型继续。",
        ],
        14,
        False,
        "E7F0FF",
        spacing=7,
    )
    add_text(slide, 7.17, 2.1, 5.3, 0.38, ["成绩口径"], 18, True, "F0A05A")
    add_text(
        slide,
        7.17,
        2.58,
        5.3,
        3.7,
        [
            "现场资料集中在 2026 年 6 月，用作历史参考。",
            "停驶短片按隧道画面风格生成，用于演示这条链路。",
            "温度没有现场序列，只作为演示假设。",
            "方案中的检测精度、轨迹指标和 30 秒端到端时限，仍是后续冻结测试的目标。",
        ],
        14,
        False,
        "E7F0FF",
        spacing=7,
    )


def slide_business(prs):
    slide = new_content(
        prs,
        "商业价值",
        "客户是运营公司和隧道管理处。收费按隧道和席位，不按泛化的大模型调用次数去讲故事。Token 省在无异常时段。",
    )
    add_lead(slide, "采购理由是少打扰的可靠提示：平时不调用，异常时给出能复核的上报建议。")
    cards = [
        ("客户是谁", "运营与值班席", "高速公路运营公司、隧道管理处、路网监测中心。第一现场是高海拔、点位多、环境特殊的隧道群。"),
        ("怎么收费", "按洞段与席位", "按隧道和监测席位收取年费，包含值守台与 Agent 调用。无异常时段不产生模型调用。"),
        ("为何能复制", "分流可以复用", "视频、气体、设备这三类源在其他洞段同样存在。换点位和规则版本，不必重做一整套对话产品。"),
    ]
    for index, (kicker, title, body) in enumerate(cards):
        add_card(slide, 0.68 + index * 4.15, 2.0, 3.95, 2.85, kicker, title, body)
    add_text(
        slide,
        0.72,
        5.15,
        12.0,
        1.0,
        ["平台侧的开发测试 Token 额度用于联调。正式运行时，成本优先和效果优先分开，把较长输出留给停驶这类安全相关事件。"],
        15,
        False,
        "E7F0FF",
    )


def slide_roadmap(prs):
    slide = new_content(
        prs,
        "落地路径",
        "左边是现在能打开页面演示的，右边是接到现场之前还要做的。不要把右侧说成已经完成。",
    )
    add_lead(slide, "原型已经能演示判断链。接到长期运行的隧道监测，还要补图像、知识库和边缘部署。")
    add_round(slide, 0.68, 2.0, 6.0, 4.5)
    add_round(slide, 6.88, 2.0, 5.8, 4.5)
    add_text(slide, 0.9, 2.16, 5.5, 0.4, ["现在可以演示"], 18, True, "7ED0A0")
    add_text(
        slide,
        0.9,
        2.68,
        5.5,
        3.55,
        [
            "现场曲线、故障记录和资料目录。",
            "一氧化碳、照度、温度、停驶的分流。",
            "多源关联与多轮追问。",
            "路由表回显模型、Token 和耗时。",
            "云端无结论时的离线备用结论。",
        ],
        16,
        False,
        "E7F0FF",
        spacing=8,
    )
    add_text(slide, 7.1, 2.16, 5.3, 0.4, ["接到现场之前"], 18, True, "F0A05A")
    add_text(
        slide,
        7.1,
        2.68,
        5.3,
        3.55,
        [
            "确认图像输入后补充视觉精判。",
            "接入养护规范和应急预案知识库。",
            "边缘节点、消息链路和分级通知。",
            "连续回放后冻结 L0–L3，再统计准确率。",
        ],
        16,
        False,
        "E7F0FF",
        spacing=8,
    )


def build():
    shutil.copyfile(TEMPLATE, OUTPUT)
    prs = Presentation(str(OUTPUT))
    build_cover(prs.slides[0])
    build_toc(prs.slides[1])
    delete_slide(prs, 3)
    delete_slide(prs, 2)
    renumber_slides(prs)

    new_section(prs, "PART  01", "Agent 简介", "用一分钟讲清问题和用户。")
    slide_problem(prs)
    slide_users(prs)
    slide_scope(prs)

    new_section(prs, "PART  02", "平台适配", "先用对照表把平台能力和本项目接法对齐，再展开策略、模型和分流。")
    slide_fit(prs)
    slide_abilities(prs)
    slide_models(prs)
    slide_routing(prs)

    new_section(prs, "PART  03", "平台应用", "先讲一次值班怎么用完平台，再讲架构、Prompt、调用和分级出口。")
    slide_apply(prs)
    slide_architecture(prs)
    slide_prompt(prs)
    slide_tools(prs)
    slide_levels(prs)

    new_section(prs, "PART  04", "效果与价值", "测试只讲已核对的行为，商业讲客户和收费，路径分现在和下一阶段。")
    slide_tests(prs)
    slide_business(prs)
    slide_roadmap(prs)

    move_to_end(prs, 2)
    thanks = prs.slides[-1]
    add_text(thanks, 0.89, 4.35, 6.8, 0.4, ["MoMA 平台适配与应用 · 隧道监测预警"], 16, False, "D5E3FA")
    thanks.notes_slide.notes_text_frame.text = "收束：Agent 把隧道值班里分散的视频、环境和设备记录，收成可以复核的上报建议。"

    prs.core_properties.title = "高海拔隧道智能监测预警 Agent"
    prs.core_properties.subject = "移动杯作品汇报"
    prs.core_properties.category = "MoMA Agent"
    prs.save(str(OUTPUT))
    print(f"saved {OUTPUT} slides={len(prs.slides)}")


if __name__ == "__main__":
    build()
