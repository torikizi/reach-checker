# OSSクレジット / Third-party notices

Reachy Mini AI Inspectorは、以下のオープンソースソフトウェアを利用しています。各プロジェクトの開発者・貢献者に感謝します。各ソフトウェアの著作権とライセンスは、それぞれの権利者に帰属します。

この一覧は、主な直接依存と映像・数値処理の基盤を示す利用案内です。依存関係全体のライセンス監査結果や、各配布物に含まれるライセンス原文・著作権表示・NOTICEの代わりではありません。依存指定は [pyproject.toml](pyproject.toml)、Macで確認したバージョンは [requirements-mac-tested.txt](requirements-mac-tested.txt) を参照してください。確認日：2026-10-31。

## 実行時に利用する主なソフトウェア

| ソフトウェア | 用途 | ライセンス・参照先 |
|---|---|---|
| [Reachy Mini SDK（`reachy-mini`）](https://github.com/pollen-robotics/reachy_mini) | 公式アプリ雛形、カメラ・音声・ロボット制御 | [Apache-2.0](https://github.com/pollen-robotics/reachy_mini/blob/main/LICENSE) |
| [FastAPI（`fastapi`）](https://fastapi.tiangolo.com/) | 検品画面のAPI | [MIT](https://github.com/fastapi/fastapi/blob/master/LICENSE) |
| [Uvicorn（`uvicorn`）](https://uvicorn.dev/) | Webサーバー | [BSD-3-Clause](https://github.com/Kludex/uvicorn/blob/main/LICENSE.md) |
| [Pillow（`pillow`）](https://python-pillow.github.io/) | 画像の読み込み・向き補正・保存 | [MIT-CMU](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |
| [OpenCV / OpenCV-Python（`opencv-python-headless`）](https://github.com/opencv/opencv-python) | 画像の前処理・特徴抽出 | OpenCV本体は [Apache-2.0](https://github.com/opencv/opencv/blob/4.x/LICENSE)、Python用ビルドスクリプトは [MIT](https://github.com/opencv/opencv-python/blob/master/LICENSE.txt)。配布パッケージの `LICENSE.txt` と `LICENSE-3RD-PARTY.txt` も参照 |
| [scikit-learn（`scikit-learn`）](https://scikit-learn.org/) | One-Class SVMの学習・推論 | [BSD-3-Clause](https://github.com/scikit-learn/scikit-learn/blob/main/COPYING) |
| [HTTPX（`httpx`）](https://www.python-httpx.org/) | Macと本体アプリの通信 | [BSD-3-Clause](https://github.com/encode/httpx/blob/master/LICENSE.md) |
| [python-multipart（`python-multipart`）](https://github.com/Kludex/python-multipart) | 正解画像のファイル受信 | [Apache-2.0](https://github.com/Kludex/python-multipart/blob/master/LICENSE.txt) |
| [NumPy（`numpy`）](https://numpy.org/) | 数値配列・音の波形生成 | [BSD-3-Clauseを中心とする複数のライセンス](https://github.com/numpy/numpy/blob/main/LICENSE.txt)。使用する配布物のライセンス一覧を参照 |
| [SciPy（`scipy`）](https://scipy.org/) | 数値計算の基盤 | [BSD-3-Clause](https://github.com/scipy/scipy/blob/main/LICENSE.txt)。同梱部品の条件も参照 |
| [GStreamer](https://gstreamer.freedesktop.org/) | Reachy SDK / daemonの映像・音声処理 | [LGPL](https://gstreamer.freedesktop.org/documentation/frequently-asked-questions/licensing.html)。プラグインと外部コーデックはそれぞれの条件を確認 |
| [PyGObject](https://pygobject.gnome.org/) | PythonからGStreamer等を利用する基盤 | [LGPL](https://gitlab.gnome.org/GNOME/pygobject/-/blob/main/COPYING)。使用する配布物の原文を参照 |

## 開発・導入・レポート作成用のソフトウェア

| ソフトウェア | 用途 | ライセンス・参照先 |
|---|---|---|
| [pytest（`pytest`）](https://docs.pytest.org/) | 自動テスト | [MIT](https://github.com/pytest-dev/pytest/blob/main/LICENSE) |
| [build（`build`）](https://build.pypa.io/) | wheel / sdist作成 | [MIT](https://github.com/pypa/build/blob/main/LICENSE) |
| [setuptools（`setuptools`）](https://setuptools.pypa.io/) | パッケージのビルド | [MIT](https://github.com/pypa/setuptools/blob/main/LICENSE) |
| [Paramiko（`paramiko`）](https://www.paramiko.org/) | 本体へのSSH開発導入 | [LGPL-2.1](https://github.com/paramiko/paramiko/blob/main/LICENSE) |
| [ReportLab（`reportlab`、任意）](https://www.reportlab.com/) | PDFレポートの作成 | [BSD License](https://pypi.org/project/reportlab/)（使用する配布物の `license.txt` を参照） |
| [uv（任意）](https://docs.astral.sh/uv/) | Python環境の準備 | [Apache-2.0 OR MIT](https://github.com/astral-sh/uv#license) |

## 配布時の扱い

- 通常のセットアップでは、依存ライブラリはPyPI等から別途インストールします。`.venv/`、`.reference/`、実機の画像・検査記録は公開対象から除外します。
- ライブラリのコード・バイナリをコピーして同梱する場合は、その使用版に付属するライセンス文、著作権表示、必要なNOTICE等を保持してください。LGPL対象物の同梱・改変・リンク形態によっては、対応ソースやライブラリの差し替え・再リンクへの対応等も必要です。このクレジット一覧だけで条件を満たしたことにはなりません。
- 動画コーデックの特許や外部プラグインの条件は、ソフトウェア本体のライセンスとは別に確認します。
- ブラウザ向けReachy JavaScript SDKの導入は現在検討段階です。導入する場合は、その採用バージョンと依存部品をこの一覧に追加します。
- この文書は第三者ソフトウェアの利用案内です。本アプリの自作部分には別の [`LICENSE`](LICENSE) に記載した MIT License を適用します。この文書によって第三者ソフトウェアのライセンスを変更するものではありません。

## 参照資料

- [Apache License 2.0：再配布条件（第4条）](https://www.apache.org/licenses/LICENSE-2.0)
- [GStreamer：ライセンスとアプリケーション](https://gstreamer.freedesktop.org/documentation/frequently-asked-questions/licensing.html)
- [GNU LGPL 2.1 原文](https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html)

製品名・プロジェクト名は識別のために使用しています。各プロジェクトによる本アプリへの推奨や認定を示すものではありません。
