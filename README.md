# ChatMate's Builder

[![Build ChatMate's](https://github.com/Haiagaru/chatmates-builder/actions/workflows/build.yml/badge.svg)](https://github.com/Haiagaru/chatmates-builder/actions/workflows/build.yml)

ChMate に [Haiagaru](https://github.com/areteruhiro/Haiagaru-Morphe) を適用し、**ChatMate's** として配布する自動ビルド用リポジトリです。
[VVispy/morphe-builder](https://github.com/VVispy/morphe-builder) の「上流パッチの更新を検知し、CLIでAPKを作成してReleaseへ公開する」構成を参考にした、独立したリポジトリです。

## ダウンロード

[Releases](https://github.com/Haiagaru/chatmates-builder/releases) から ChMate の版と構成を選びます。

| ファイル末尾 | Shizuku 移行パッチ | MEGA バックアップ・同期 |
|---|---|---|
| `plain.apk` | なし | なし |
| `shizuku.apk` | あり | なし |
| `mega.apk` | なし | あり |
| `shizuku-mega.apk` | あり | あり |

対象は `0.8.10.191 dev`、`0.8.10.226 dev`、`0.8.10.242 dev`。1つの Haiagaru リリースから計12 APKを生成します。基本パッチは `Haiagaru` と `Change ChMate package name` です。その他の任意パッチは追加しません。

- アプリ表示名: **ChatMate's**
- Android パッケージID: `io.github.haiagaru.chatmates`
- versionCode: `2147483647`（上流パッチの既定値。対応する ChMate 版と構成の切り替えに使用）
- 全構成で共通の、このリポジトリ専用の署名鍵を使用

`ChatMate's` はアポストロフィを含むため Android パッケージIDには使えず、表示名として設定します。12 APKは同じパッケージIDを持つため、同時にインストールするのは1つです。元の ChMate とは別アプリとして共存できます。Shizuku または MEGA を含む構成は Android 7.0 以降が必要です。

## 更新検知

GitHub Actions が **15分間隔**で `areteruhiro/Haiagaru-Morphe` の GitHub Releases を確認します。GitHub 側の混雑で開始が遅れる場合があります。

- 初回は最新の正式リリースをビルドします。
- `chatmates.json` の `monitor_since` 以降に公開された正式版・プレリリースを、それぞれ検知してビルドします。同じ確認間隔内の複数リリースも対象です。
- Release 公開後に MPP がアップロードされた場合も、次回確認で対象にします。
- パッチ配布ファイルの差し替え、構成変更も識別し、既に成功・公開した同じ構成は再ビルドしません。
- 12 APK がすべて成功した場合に Release を公開します。途中の失敗は次回確認で再試行します。プレリリースは出力側も Pre-release とします。
- 未完成の Draft、MPP のない Release はビルドしません。

[Actions](https://github.com/Haiagaru/chatmates-builder/actions/workflows/build.yml) → **Run workflow** から手動実行できます。`channel` は `all` / `stable` / `prerelease`、`force` で公開済みの構成も作り直せます。

監視対象は **Haiagaru パッチのリリース**です。ChMate の対象APKは、指定された3ファイルを固定して使用します。

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
