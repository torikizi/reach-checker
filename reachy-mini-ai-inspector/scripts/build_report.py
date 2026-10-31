#!/usr/bin/env python3
"""Generate the clearly marked progress-report draft; no personal information."""
from pathlib import Path
import argparse
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/pdf/reachy-mini-ai-inspector-report-draft.pdf'
OUT.parent.mkdir(parents=True,exist_ok=True)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--font', type=Path, default=Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf'), help='Japanese TrueType font to embed (macOS default: Arial Unicode)')
args = parser.parse_args()
if not args.font.is_file():
    parser.error('Japanese TrueType font not found; specify --font /path/to/font.ttf')
pdfmetrics.registerFont(TTFont('Japanese', str(args.font)))
INK=colors.HexColor('#253e34'); MUTED=colors.HexColor('#667369'); LINE=colors.HexColor('#d5dfd3')
base=ParagraphStyle('body',fontName='Japanese',fontSize=9.3,leading=16,textColor=INK,wordWrap='CJK',spaceAfter=9)
small=ParagraphStyle('small',parent=base,fontSize=7.5,leading=12,textColor=MUTED)
heading=ParagraphStyle('heading',parent=base,fontSize=15,leading=22,spaceBefore=14,spaceAfter=10)
title=ParagraphStyle('title',parent=base,fontSize=29,leading=35,spaceAfter=18)
label=ParagraphStyle('label',parent=small,fontSize=9,leading=14,spaceAfter=12,textColor=colors.HexColor('#b45e31'))
story=[]
def p(text,style=base): story.append(Paragraph(text,style))
def table(rows,widths):
    formatted=[[Paragraph(str(c),small if i else base) for c in r] for i,r in enumerate(rows)]
    t=Table(formatted,colWidths=widths,hAlign='LEFT')
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e8eee4')),('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,-1),.45,LINE),('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
    story.append(t);story.append(Spacer(1,9))
def footer(c,doc):
    c.saveState();c.setStrokeColor(LINE);c.line(44,47,551,47);c.setFont('Japanese',7);c.setFillColor(MUTED);c.drawString(44,32,'検証途中版 / 2026-10-31更新 / 物体判別・環境光実験の計画版');c.drawRightString(551,32,str(doc.page));c.restoreState()

p('PHYSICAL AI  /  DEVELOPMENT REPORT  /  DRAFT',label)
p('Reachy Mini<br/>AI Inspector',title)
p('Reachy Miniによる物体判別と<br/>環境光の影響を調べる。',heading)
p('本資料は開発途中の報告書です。公式アプリの導入、実カメラ映像、Controlからの起動停止は確認済みです。実物LEGOの学習・検出精度と物理リアクションは未確認で、提出用の最終版ではありません。')
story.append(Image(str(ROOT/'doc/dashboard-demo.jpg'),width=507,height=285.19,kind='proportional'))
p('図1　合成画像によるダッシュボード。赤色2×8を形状違いとしてNGと表示。実物の評価結果ではない。',small)
p('1. 目的と対象',heading)
p('Reachy Mini Wirelessの内蔵カメラで検査台のブロックを撮影し、MacでAI推論を行う。レゴ10696に合わせ、正常品は赤色2×4、規格外品は青色2×4（色違い）と赤色2×8（形状違い）。人が1個ずつ交換し、PC画面から検査する。')
p('本実験の目的は、①固定した撮影条件で対象物の違いを判別できるか、②環境光の明るさや向きが変わると判別性能が低下するか、の2点を調べることである。任意の物体の名前を認識する実験ではなく、登録した正常品と色・形状の異なる物体を区別する実験とする。')
story.append(PageBreak())
p('SYSTEM & METHOD',label)
p('2. 構成と制御の分担',heading)
table([['場所','担当'],['本体 daemon + 公式アプリ','daemonが物理カメラ・モーターを所有。ReachyMiniAppがSDKローカルIPCから画像を読み、JPEG配信と固定リアクションを担当する。'],['Mac Python','OpenCV前処理、One-Class SVM学習・推論、判定、画像とSQLite履歴、CSV。'],['Macブラウザ','ライブ映像、ROI、識別名、OK/NG/REVIEW、正常登録、閾値、履歴と正解ラベル。']], [118,389])
p('本体を唯一のSDK操作主体とし、Macはトークン付きLANブリッジへ接続する。実機モードと合成デモを分離し、接続失敗時にデモへ自動切替しない。SDKとDaemonは1.12.0で検証した。')
p('3. AI異常検知',heading)
p('彩度に基づく対象抽出後、色ヒストグラム18成分、回転矩形の縦横比、占有面積、充填率、彩度・明度を特徴にする。正常画像8枚以上でOne-Class SVM（RBF、gamma=1.2、nu=0.08）を学習し、検査ごとにscore_samplesとdecision_functionを実行する。')
p('異常スコア = clip（1 - 検査画像のscore_samples / 正常学習画像のscore_samples中央値, 0, 1）。低いほど正常に近い。スコアは確率ではない。初期閾値はOK: 0.38以下、NG: 0.68以上であり、実物での調整が必要。')
p('品質が適切な画像のAIスコアで判定し、色・投影形状の差を補助的な理由として表示する。対象なし、複数対象、ぼけ、枠外、未学習、判定の矛盾はREVIEWとする。単純なRGB閾値だけをAIとして扱わない。')
p('4. 動作・記録の工夫',heading)
p('撮影 → 固定画像でAI推論 → 画像と判定を保存 → リアクション → 基本姿勢復帰 → 静止待ち、の順で直列処理する。OKはうなずき、NGは左右振り、REVIEWは首の傾き。各区間0.8秒のminjerk、小角度のみを許可する。')
p('モーションは起動時OFF。有効化時の撮影姿勢を保持し、動作後も画角を保つ。切断・例外・通信許可失効時は無効化。途中停止後は姿勢復帰まで検査を保留する。識別名、時刻、画像、理由、スコア、モデルID、設定、動作結果を保存し、後から追跡できる。')
story.append(PageBreak())
p('EXPERIMENT PLAN',label)
p('5. 実験1：固定条件での物体判別',heading)
p('背景、撮影距離、カメラ角度、物体の位置、照明を固定する。正常品の赤色2×4を異なる画像で12〜20枚登録し、閾値の調整には評価用とは別の画像を使う。モデルと閾値を確定してから本評価を始める。')
p('学習に使わない撮り直し画像で、赤色2×4、青色2×4、赤色2×8を各30回、計90回検査する。1回ごとに物体を置き直し、順番を入れ替える。期待判定は順にOK、NG、NGとし、同じ画像の再送を独立した試行として数えない。')
p('6. 実験2：環境光の変化による影響',heading)
p('実験1と同じモデル・閾値を使い、再学習せずに比較する。撮影距離、背景、角度、位置をそろえ、照明だけを基準、暗い、明るい、逆光の4条件に変える。各条件で3種類を各30回、合計360回検査する。基準条件は実験1の90回を共用できる。')
table([['照明条件','設定と記録'],['基準','学習時と同じ照明。照明器具、向き、距離、カメラ設定を記録。'],['暗い / 明るい','基準と同じ向きで光量を下げる / 上げる。照度計があれば物体位置のlxを記録。'],['逆光','物体の背後から照射する。光源の位置と向き、可能なら照度を記録。']], [118,389])
p('カメラの露出・ホワイトバランスを固定できる場合は全条件で固定する。自動の場合はその旨を記録し、照明変更後に映像が安定してから撮影する。条件の順序を入れ替え、最後に基準条件へ戻して変化を確認する。')
p('7. 評価指標と結果の記入',heading)
p('各試行の画像、物体の種類、照明条件、人による正解、OK/NG/REVIEW、スコア、処理時間、モデルIDを残す。条件別・物体別に判定数を集計し、正判定率＝期待判定と一致した回数÷全試行数、REVIEW率＝REVIEW数÷全試行数を求める。REVIEWも分母に含める。')
p('正常品をNGとした誤検出、規格外品をOKとした見逃しも別に示す。基準条件との差はパーセントポイントで比較する。暗所や逆光で正判定率が下がり、REVIEWや誤判定が増えるという仮説を検証する。差が出なかった場合も、そのまま結果として報告する。')
p('実物実験は未実施のため、現時点では正判定率や環境光による性能低下を結論にしない。',label)
story.append(PageBreak())
p('VALIDATION & NEXT STEPS',label)
p('8. これまでの動作確認（実験結果とは別）',heading)
table([['検証層','結果'],['自動テスト','23件合格（10/22）。赤2×8の形状NGと枠切れREVIEWを含む。AI、保存、切断、競合、動作範囲・停止を検証。モーターはFake SDK。'],['公式CLI','v0.1.0で構造、独立環境へのインストール、entry point登録、アンインストールが合格（10/21）。'],['実機 / Mac','v0.1.0で本体導入、Controlから停止・再起動、Macに960×540の実画像を表示（10/21）。新規静止画3枚、241 / 293 / 388 ms。'],['ブラウザ','合成正常品で学習し、赤2×4・青2×4・赤2×8の判定と画像付き履歴を確認（10/22）。CSV・正解ラベルは10/21に確認済み。']], [118,389])
p('合成画像の回帰評価：正常学習12枚とは異なるseedで各30枚。',small)
table([['合成条件','期待判定','結果'],['赤2×4 / 青2×4 / 赤2×8','OK / NG / NG','各30件が期待判定'],['対象なし / ぼけ','REVIEW / REVIEW','各30件が期待判定']], [238,134,135])
p('合成画像150件の一致は、実物LEGOの精度を示さない。実物の正常検出率、異常検出率、見逃し、REVIEW率は未測定。',label)
p('9. 考察の観点と残る作業',heading)
p('採用した本体IPC→JPEG方式では実カメラを取得できた。一方、Macから直接SDKのWebRTC映像を受ける方式はGStreamer初期化でタイムアウトしたため、主経路にしなかった。照明、距離、投影形状への依存があり、白黒ブロックや傷・割れ検出は対象外である。')
p('実験1で固定条件下の判別性能を確認し、実験2で照明条件ごとの差を調べる。色・明度や影、白飛び、対象抽出の変化と誤判定画像を対応させて考察する。性能低下が見られた場合は、照明の固定や複数照明条件での学習を改善案とする。物理リアクションは追加の動作実演として扱う。')
p('10. 参照資料・提出',heading)
p('公式SDK / AGENTS.md: github.com/pollen-robotics/reachy_mini<br/>公式アプリガイド: huggingface.co/docs/reachy_mini/SDK/apps<br/>メディア構成: huggingface.co/docs/reachy_mini/SDK/media-architecture<br/>参照日 2026-10-21。再現手順と詳細ログはソースのdoc/setup.mdとdoc/validation.md。',small)
p('残る提出物：実物評価を反映したPDF最終版、GitHub public、1〜3分のYouTube動画、OmniCampusと優秀生選出用の提出。公開前に個人情報・実画像の映り込み・トークンを確認する。',small)
doc=SimpleDocTemplate(str(OUT),pagesize=A4,rightMargin=44,leftMargin=44,topMargin=42,bottomMargin=63,title='Reachy Mini AI Inspector - 開発レポート下書き',author='',subject='実物LEGO評価前の検証途中版')
doc.build(story,onFirstPage=footer,onLaterPages=footer)
print(OUT)
