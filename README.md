# GUInuplot
Gnuplotの直感的な操作を可能にしたGUIアプリケーションです．

## 出力可能なグラフ
今のところ2次元,3次元のプロットのみに対応しています．ベクトルのプロットも可能です．今後はヒストグラム等にも対応させる予定です．

## 対応ファイル
.dat, .txt

## 使い方
### Plot Mode
    Mode: 2D Plotと3D Plotの2種類があります．

### 1. Add New Plot
グラフに描画するデータファイルを追加し，初期設定を行います．

    File Selection: 点線のエリアにファイルをドラッグ＆ドロップするか，「Browse...」ボタンから読み込むファイル（.dat, .txt）を選択します．

    Add as Vector Plot: ベクトル図（矢印プロット）として描画したい場合にチェックを入れます．

    Add as Static Object (Model): 面や線などのデータではないオブジェクト（ワイヤーフレーム等）を入れたい場合にチェックを入れます．これはカラーバーの計算範囲から除外され，単色（デフォルトはグレー）で表示されます．

    Columns (using): ファイル内のどの列データを x, y, (z) やベクトル成分として使用するかを指定します．

    Target Axis: （2Dモードのみ）プロットの縦軸を左側の主軸（Y1-Axis）にするか，右側の副軸（Y2-Axis）にするかを選択します．

    Add Plot to Tabs: 設定が完了したらこのボタンをクリックしてください．右側のプレビューにグラフが表示され，編集用のタブが追加されます．

### 2. Current Plots (Edit in Tabs)
「Add Plot」で追加されたデータはタブとして管理されます．各タブ内で以下の詳細設定を変更可能です．

    Plot Details: 凡例に表示されるタイトルや，using（列指定）の修正が可能です．

    Static Model Mode: 「Static Model Mode」にチェックを入れると，そのプロットは物体モデルとして扱われ，カラーバーの計算範囲から除外されます（単色表示になります）．

    Plot Style: 点や線のスタイル（lines, points, pm3d等），サイズ，色などを変更できます．

    Vector Options: ベクトル表示の場合，矢印のスタイル，ヘッドサイズ，スケーリング，正規化（Normalize）の設定が可能です．

### 3. General Graph Settings

    グラフ全体のタイトルを設定します．チェックボックスを有効にすることでタイトルが反映されます．
### 4. Axis Settings

各軸（X, Y1, Y2, Z）の詳細設定を行います．

    Label: 軸のラベルを設定します．

    Range: 描画範囲（xrange, yrange等）を手動で固定します．

    Tics Offset: 目盛りの数値の位置を微調整します．

    Log Scale: 対数軸の有効・無効を切り替えます．

    Grid: グリッド線の表示有無を設定します（X軸タブ内）．

### 5. View & Map Settings (3D)

3D Plotモード選択時のみ表示されます．

    Rotate: スライダーを用いて視点の角度（X軸周り，Z軸周り）を調整します．

    pm3d: 曲面描画（pm3d）の有効・無効を切り替えます．

    Fix XY Plane: Z軸の底面（xyplane）の位置を数値で固定します．

### 6. Output Settings

出力画像および凡例，カラーバーに関する設定を行います．

    General Output: 画像サイズ（幅×高さ）およびフォントの種類・サイズを指定します．

    Legend (Key): 凡例の表示位置，最大行数・列数を指定します．

    Color Box Settings: カラーバーの表示有無，ラベル，範囲（cbrange），サイズ，配置位置を設定します．数値を 10x 形式で表示するオプションも利用可能です．

### メニューバー機能

画面上部のメニューバーから以下の操作が可能です．
File

    Export Project...: 現在の設定に基づき，PNG画像，Gnuplotスクリプト（.gp），C言語ソース（.c）を一括して指定フォルダにエクスポートします．

    Save Graph As...: 現在のグラフを画像ファイル（PNG, SVG, PDF）として保存します．

    Save Script As (.gp)...: 現在の描画コマンドをGnuplotスクリプト形式で保存します．

    Save for C Language As (.c)...: C言語の popen 関数を用いてGnuplotを呼び出す形式のソースコードを出力します．

    Save Settings... / Load Settings...: 現在のGUI上の設定値をJSON形式で保存・読み込みします．