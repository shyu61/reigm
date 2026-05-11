---
name: note-article-review
description: Review a draft note article for the unique real estate data journalism media context — written for industry professionals (real estate tech execs, journalists, analysts, investors), not general consumers. Use this skill whenever the user shares a note draft and asks for review, critique, feedback, or improvement suggestions. Also trigger when the user pastes article text and asks "どう？" "レビューして" "批評して" "改善点は？" or similar. Apply this even if the user doesn't explicitly mention "note" — if the content looks like a Japanese long-form article with data/charts intended for a business audience, use this skill. Do NOT use for general writing feedback unrelated to the real estate data journalism media context.
---

# Note Article Review Skill

業界人向け不動産データジャーナリズム記事のレビュー専用skill。

## このskillの目的

ユーザーが書いた記事ドラフトを、業界人（不動産テック企業幹部・業界紙記者・アナリスト・投資家）に刺さるかという観点でレビューする。AIライティングの平均的フィードバック（「もっと分かりやすく」「読者に寄り添って」等）は**禁止**。業界人向け専門記事の文脈に特化した批評を行う。

## レビューの大原則

**書き手は「業界の中の人」として読み手と対等に向き合う**。読者を子供扱いしない、定義から入らない、断定する、視点を明確にする。

**目的は「読まれる」ことではなく「業界キーパーソンに引用・共有される」こと**。バズ狙いの toC 攻略法（感情訴求タイトル、共感ベース構成等）は適用しない。

**書き手にしか書けない記事になっているか**を最重視する。AIで生成できる平均的な構成は、それ自体が失敗のシグナル。

## レビュー実行プロセス

以下の3段階で進める。**必ずこの順序で**実施する。

### Step 1: 全体読み込みと第一印象

記事全体を最後まで読んだ上で、以下を内的に判定する（この段階では出力しない）：

- 業界人が冒頭3段落で離脱せずに読み進めるか
- 「この人にしか書けない」要素があるか、それとも「AIでも書けそう」か
- 切り口に「業界の通説に対する違和感」が含まれているか
- データから出された結論にエッジが効いているか、それとも両論併記で逃げているか

### Step 2: 詳細レビュー（references/review-checklist.md を参照）

詳細なレビュー観点は `references/review-checklist.md` に格納してある。必ずこのファイルを `view` で読んでから本格的なレビューに入る。

チェックリストの各項目について、原稿の該当箇所を引用しながら具体的に評価する。**抽象的な指摘は禁止**（「もっと具体的に」「分かりやすく」等は NG）。

### Step 3: 構造化された出力

以下のフォーマットで出力する：

```markdown
# レビュー結果

## 総合評価
[業界人に刺さるか、現状の完成度を一言で]

## ✅ 強み（残すべき要素）
[書き手の独自性が出ている箇所を具体的に引用して指摘。3-5項目]

## ⚠️ 致命的な問題（公開前に必ず直す）
[業界人読者が離脱・失望する要因。引用 + 修正方針。0-3項目]

## 🔧 改善推奨（質を一段上げる）
[強みを更に強める or 弱点を補強する提案。引用 + 具体的な書き換え案。3-7項目]

## 💡 切り口の検討
[現状の切り口を更に強化する追加の分析角度、または対案]

## 📊 chart・データ表現
[chart の見せ方、データの解釈に関する指摘]

## 🐦 X投稿用の抜粋候補
[note記事から抜粋して X 用に展開できる強い箇所を3-5個提案]
```

## レビュー時の禁止事項

以下のフィードバックは絶対に出さない（出てきたら自己検閲する）：

- 「もっと読者に分かりやすく」（業界人読者は十分に賢い）
- 「専門用語の定義を入れましょう」（業界人には不要）
- 「両論併記でバランスを取りましょう」（書き手の視点こそが価値）
- 「結論を断定せず可能性として示唆しましょう」（プロは断定する）
- 「もっと感情に訴える表現を」（業界人向けでは逆効果）
- 「SEOキーワードを意識しましょう」（このメディアの集客チャネルは SEO ではない）
- 「導入で自己紹介を」（中身で語る）
- 「読者の悩みに寄り添う冒頭に」（toC 攻略法）
- 抽象的褒め言葉のみ（「良い記事です」「興味深いです」等）

## 補足: スタイル

- レビューする側として、率直に書く。空気を読んでマイルドにしない
- ただし、書き手を尊重する。「書き直すべき」より「こう変えるとさらに強い」の言い方を選ぶ
- 引用は原文の正確な抜粋。改変しない
- 修正案は「こう書くとどうか」と具体的に提示する。抽象的な方向性だけで終わらせない
