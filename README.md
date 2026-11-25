# ChatMate's Builder

[![Build ChatMate's](https://github.com/Haiagaru/chatmates-builder/actions/workflows/build.yml/badge.svg)](https://github.com/Haiagaru/chatmates-builder/actions/workflows/build.yml)

ChMate に [Haiagaru](https://github.com/areteruhiro/Haiagaru-Morphe) を適用し、**ChatMate's** として配布する自動ビルド用リポジトリです。
[VVispy/morphe-builder](https://github.com/VVispy/morphe-builder) の「上流パッチの更新を検知し、CLIでAPKを作成してReleaseへ公開する」構成を参考にした、独立したリポジトリです。

## ダウンロード

[Releases](https://github.com/Haiagaru/chatmates-builder/releases) から ChMate の版を選びます。191／226／242 dev の各版につき、ll-enabled.apk を1本ずつ公開します（計3 APK）。

全APKで Shizuku、MEGA、画像判定モデル・実行ライブラリ、画像取得専用VPN、動画専用ビューア、クラッシュログ保存を有効にします。191にはImage NG修正ライブラリも組み込みます。機能の利用には Android 7.0（API 24）以上が必要です。クラッシュ・ANRログの送信はアプリ内の同意設定に従います。

ライブラリはMPPと同じ上流Releaseから取得します。画像判定・VPNの一括ZIPがあれば両パッチに指定し、191用Image NG修正ZIPも取得します。一括ZIPがなければ個別ZIPを使用します。SHA-256を照合し、配布URLとハッシュを uild-*.json に記録します。必要なファイルが不足したReleaseは公開しません。

- アプリ表示名: **ChatMate's**
- Android パッケージID: `io.github.haiagaru.chatmates`
- versionCode: `2147483647`（上流パッチの既定値。対応する ChMate 版と構成の切り替えに使用）
- 全構成で共通の、このリポジトリ専用の署名鍵を使用

`ChatMate's` はアポストロフィを含むため Android パッケージIDには使えず、表示名として設定します。全APKは同じパッケージIDを持つため、同時にインストールするのは1つです。元の ChMate とは別アプリとして共存できます。Shizuku または MEGA を含む構成は Android 7.0 以降が必要です。

動画専用ビューアあり版の末尾は `-video-viewer.apk` です。画像判定あり・なしの各構成に用意します。導入後もHaiagaru設定から動画専用ビューアをオン／オフできます。必死チェッカー専用ビューアはHaiagaruのメインパッチに含まれ、アプリ内設定でON／OFFを切り替えます。OFFの場合はChMateのWeb表示で開きます。

## 更新検知

GitHub Actions が **5分間隔**で `areteruhiro/Haiagaru-Morphe` の GitHub Releases を確認し、新しい正式版・プレリリースのMPPを検知したら自動ビルドします。GitHub Actionsの定期実行で設定できる最短間隔です。定期実行の開始はGitHub側の混雑で遅れる場合があるため、公開から5分以内の開始を保証するものではありません。

- 初回は最新の正式リリースをビルドします。
- `chatmates.json` の `monitor_since` 以降に公開された正式版・プレリリースを、それぞれ検知してビルドします。同じ確認間隔内の複数リリースも対象です。
- Release 公開後に MPP がアップロードされた場合も、次回確認で対象にします。
- パッチ配布ファイルの差し替え、構成変更も識別し、既に成功・公開した同じ構成は再ビルドしません。
- 対象の全APK（画像判定対応版は48 APK）が成功した場合に Release を公開します。途中の失敗は次回確認で再試行します。プレリリースは出力側も Pre-release とします。
- 未完成の Draft、MPP のない Release はビルドしません。

[Actions](https://github.com/Haiagaru/chatmates-builder/actions/workflows/build.yml) → **Run workflow** から手動実行できます。`channel` は `all` / `stable` / `prerelease`、`force` で公開済みの構成も作り直せます。

監視対象は **Haiagaru パッチのリリース**です。ChMate の対象APKは、指定された3ファイルを固定して使用します。

### Issueから更新を要求する

[このリポジトリのIssues](https://github.com/Haiagaru/chatmates-builder/issues)で、Issueのタイトル・本文、またはコメントに **`更新` の一語だけ**を投稿すると、投稿イベントで直接ワークフローを起動し、最新の配布済みMPPを使って全構成を再ビルドします。定期確認を待つ必要はありません。編集による「更新」の入力にも対応します。パッチの取得元は `areteruhiro/Haiagaru-Morphe` です。正式版・プレリリースを含め、公開日時が最も新しいものを選びます。「更新するとクラッシュする」などの文章、Pull Requestとそのコメントは対象外です。前後に空白・改行がある投稿は定期確認で検知します。

`issue-watch.json` の `since` 以降に作成・編集された投稿が対象です。同じIssueまたはコメントは公開成功後に再実行しません。失敗時は次の確認で再試行します。要求元のURLはReleaseとビルド記録に保存します。投稿への返信・書き込みは行いません。定期確認は5分間隔で設定していますが、GitHub側のスケジュール遅延により、実際には数十分以上空く場合もあります。投稿イベントにもランナー待ちが発生する場合があります。

## 追跡と再現

設定は [`chatmates.json`](chatmates.json)、処理は [`scripts/builder.py`](scripts/builder.py) にあります。Morphe CLI は版と SHA-256 を固定し、元APKも SHA-256 を照合します。Release に `SHA256SUMS` と `build-191.json` / `build-226.json` / `build-242.json` を添付し、パッチ、CLI、元APK、構成、ビルドコミット、署名証明書を記録します。

元APKは `source-apks` Release の Assets から取得します。この Release はビルド済みアプリの最新版には指定しません。APK を変更する場合は元ファイルと設定の SHA-256 を一緒に更新します。

## 管理者向け

Actions の Repository secrets に以下を登録します。

| Secret | 内容 |
|---|---|
| `CHATMATES_KEYSTORE_BASE64` | PKCS12 署名鍵の Base64。alias は `chatmates` |
| `CHATMATES_KEYSTORE_PASSWORD` | 署名鍵のパスワード |

鍵の証明書 SHA-256 は `chatmates.json` の `signer_sha256` と照合します。鍵を変更すると既存の APK へ上書き更新できなくなるため、鍵とパスワードをバックアップしてください。秘密鍵はソース、Release、Artifact に含めません。

Signing keys and passwords are stored locally in `.signing`. Original APKs in `inputs`, downloaded files in `.work`, and `.signing` are excluded from Git.

## Credits / License

- パッチ: [areteruhiro/Haiagaru-Morphe](https://github.com/areteruhiro/Haiagaru-Morphe)
- パッチ適用・署名: [MorpheApp/morphe-cli](https://github.com/MorpheApp/morphe-cli)
- ビルド構成の参考: [VVispy/morphe-builder](https://github.com/VVispy/morphe-builder) / [j-hc/revanced-magisk-module](https://github.com/j-hc/revanced-magisk-module)

このリポジトリのビルド用コードは GPL-3.0（[LICENSE](LICENSE)）です。ChMate、本体に適用するパッチ、依存物にはそれぞれのライセンスが適用されます。
