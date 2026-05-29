# ColorUtils

一个基于效果栈的 Lospec 调色盘和像素图像处理工具。

## 功能

- 左侧提供操作库和当前效果栈，效果栈可以拖拽调整顺序。
- 效果按 stack 顺序实时应用到 Preview。
- 动态加载 Lospec 调色盘列表，支持分页加载和排序。
- 已加载的 Lospec 列表、搜索结果和调色盘会缓存到 `~/.colorutils/lospec_cache.json`，下次打开优先读缓存。
- Lospec 参数面板会先加载多页填满列表，滚动到底部附近会自动继续加载。
- 输入关键词搜索特定 Lospec 调色盘。
- `Lospec Recolor` 可以作为 stack 中任意一步，将当前图像映射到指定 Lospec 调色盘最近颜色。
- 支持在换色后继续叠加 `Gaussian 3x3`、`Laplace`、`Sobel`、`Erosion`、`Dilation`、`Pixelize`、`Pixel Perfect`。
- 中间区域使用 Tab 切换 `Original`、`Preview`、`Stats`。
- 窗口缩放时只做延迟刷新，避免拖动窗口过程中连续重绘。
- 保存 stack 处理后的图片。
- Stats Tab 提供 RGB 直方图和基础图片统计。

## Stack 操作

- Lospec Recolor：最近色调色盘映射。
- Gaussian 3x3：3x3 高斯卷积，可调迭代和强度。
- Laplace：拉普拉斯卷积，可输出边缘或叠加回原图。
- Sobel：Sobel 边缘，可灰度输出或叠加。
- Erosion / Dilation：腐蚀和膨胀，可调 kernel size 和迭代次数。
- Pixelize：多种像素化算法。
- Pixel Perfect：最近邻硬边缩放 + 可选色阶吸附。

## Pixelize 算法

- Average Blocks：按块求平均色再放大。
- Median Blocks：按块求中位数颜色，抗噪声更强。
- Nearest Resize：最近邻缩小再放大，保留硬边采样感。
- Posterize：降低色阶后块状放大。
- Ordered Dither：Bayer 有序抖动，可调强度。

## 安装和运行

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m colorutils.app
```

项目需要 Python 3.10 或更新版本。这台机器可以使用 `py -3.10` 创建虚拟环境。

## 使用

1. 点击 `Open Image` 选择图片。
2. 在左侧 `Operations` 中双击或点击 `Add To Stack` 添加操作。
3. 选择 stack 中的某一步，在右侧调整参数。
4. 如果添加 `Lospec Recolor`，在右侧搜索或滚动选择 Lospec 调色盘。
5. 拖拽 stack 中的步骤调整顺序，Preview 会自动更新。
6. 点击 `Save Stack Result` 保存当前 stack 处理结果。

首次加载 Lospec 列表和搜索需要联网。程序会把已经加载过的数据缓存在本地磁盘中；点击 `Refresh` 会绕过缓存并从 Lospec 拉取最新数据。
