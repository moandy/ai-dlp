"""
屏摄图片几何校正算法 - 基于 tile 平铺自相关特性
=============================================

核心思路：
1. 水印以 267x267 的二值 tile 周期性平铺在屏幕上
2. 拍摄后图片具有（变形的）周期性
3. 通过分块自相关/FFT 检测局部周期向量
4. 周期向量的空间变化反映透视变形 → 求单应性矩阵 H
5. 全图校正后提取水印

测试攻击场景：
- 透视变形（多角度）
- JPEG 压缩（不同质量）
- 高斯噪声
- 亮度/对比度变化
- 组合攻击
"""

import sys
import os
import io
import time
import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage, signal
from scipy.fft import fft2, ifft2, fftshift

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

np.random.seed(42)

# ==================== 常量 ====================
TILE_SIZE = 267
WATERMARK_ALPHA = 3  # 透明度 3/255
SCREEN_W, SCREEN_H = 1920, 1080


# ==================== 1. 水印生成与嵌入 ====================

def generate_binary_tile(size=TILE_SIZE, seed=12345):
    """生成随机二值水印 tile (0 或 255)"""
    rng = np.random.RandomState(seed)
    tile = (rng.randint(0, 2, (size, size)) * 255).astype(np.uint8)
    return tile


def tile_watermark_on_screen(tile, screen_w=SCREEN_W, screen_h=SCREEN_H):
    """将 tile 平铺到整个屏幕大小"""
    th, tw = tile.shape[:2]
    rows = (screen_h + th - 1) // th
    cols = (screen_w + tw - 1) // tw
    tiled = np.tile(tile, (rows, cols))
    return tiled[:screen_h, :screen_w]


def embed_watermark(content_img, watermark_layer, alpha=WATERMARK_ALPHA):
    """
    将水印层嵌入到内容图像中
    content_img: (H, W, 3) uint8
    watermark_layer: (H, W) uint8, 0 或 255
    alpha: 透明度 0~255
    """
    result = content_img.astype(np.float64)
    wm = watermark_layer.astype(np.float64)
    a = alpha / 255.0
    for c in range(3):
        result[:, :, c] = result[:, :, c] * (1 - a) + wm * a + result[:, :, c] * a * (1 - wm / 255.0)
    # 简化: result = content * (1-a) + wm * a
    result = content_img.astype(np.float64)
    for c in range(3):
        result[:, :, c] = result[:, :, c] + (wm - result[:, :, c]) * a
    return np.clip(result, 0, 255).astype(np.uint8)


def generate_screen_content(w=SCREEN_W, h=SCREEN_H):
    """生成模拟屏幕内容（有文字块、色块等结构化内容）"""
    img = np.ones((h, w, 3), dtype=np.uint8) * 240  # 浅灰背景

    rng = np.random.RandomState(99)
    # 模拟窗口/文字区域
    for _ in range(15):
        x1, y1 = rng.randint(0, w - 200), rng.randint(0, h - 100)
        x2, y2 = x1 + rng.randint(100, 400), y1 + rng.randint(50, 200)
        x2, y2 = min(x2, w), min(y2, h)
        color = rng.randint(20, 230, 3).tolist()
        img[y1:y2, x1:x2] = color

    # 模拟文字行（深色水平条纹）
    for _ in range(30):
        y = rng.randint(0, h - 12)
        x = rng.randint(0, w - 300)
        length = rng.randint(100, 500)
        thickness = rng.randint(8, 16)
        gray = rng.randint(10, 80)
        img[y:y + thickness, x:x + min(length, w - x)] = gray

    return img


# ==================== 2. 攻击模拟 ====================

def apply_perspective_transform(img, severity="medium"):
    """
    模拟透视变形（屏摄拍摄角度）
    severity: light / medium / heavy
    """
    h, w = img.shape[:2]
    params = {
        "light":  0.03,
        "medium": 0.08,
        "heavy":  0.15,
    }
    s = params.get(severity, 0.08)

    rng = np.random.RandomState(7)
    # 四个角的偏移
    offsets = rng.uniform(-s, s, (4, 2))

    src_pts = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
    dst_pts = src_pts.copy()
    dst_pts[:, 0] += offsets[:, 0] * w
    dst_pts[:, 1] += offsets[:, 1] * h

    # 确保目标点在合理范围
    dst_pts[:, 0] = np.clip(dst_pts[:, 0], -w * 0.2, w * 1.2)
    dst_pts[:, 1] = np.clip(dst_pts[:, 1], -h * 0.2, h * 1.2)

    # 计算输出大小
    x_min, y_min = dst_pts.min(axis=0)
    x_max, y_max = dst_pts.max(axis=0)
    out_w = int(x_max - x_min)
    out_h = int(y_max - y_min)

    # 平移使所有点为正
    dst_pts[:, 0] -= x_min
    dst_pts[:, 1] -= y_min

    # 手动计算透视变换矩阵 (不依赖 cv2)
    M = compute_perspective_matrix(src_pts, dst_pts)

    result = warp_perspective(img, M, out_w, out_h)
    return result, M, src_pts, dst_pts


def compute_perspective_matrix(src, dst):
    """
    从 4 对点计算 3x3 透视变换矩阵
    使用 DLT (Direct Linear Transform) 算法
    """
    A = []
    for i in range(4):
        x, y = src[i]
        u, v = dst[i]
        A.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
        A.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
    A = np.array(A, dtype=np.float64)
    _, _, Vt = np.linalg.svd(A)
    H = Vt[-1].reshape(3, 3)
    H /= H[2, 2]
    return H


def warp_perspective(img, M, out_w, out_h):
    """用透视矩阵 M 变换图像（纯 numpy 实现）"""
    if img.ndim == 2:
        img = img[:, :, np.newaxis]
    h, w, c = img.shape
    result = np.zeros((out_h, out_w, c), dtype=img.dtype)

    M_inv = np.linalg.inv(M)

    # 构建输出像素网格
    ys, xs = np.meshgrid(np.arange(out_h), np.arange(out_w), indexing='ij')
    ones = np.ones_like(xs)
    dst_coords = np.stack([xs, ys, ones], axis=-1).reshape(-1, 3).T  # (3, N)

    # 反向映射到源图
    src_coords = M_inv @ dst_coords.astype(np.float64)
    src_coords /= src_coords[2:3, :]  # 齐次坐标归一化

    sx = src_coords[0].reshape(out_h, out_w)
    sy = src_coords[1].reshape(out_h, out_w)

    # 双线性插值
    sx0 = np.floor(sx).astype(np.int64)
    sy0 = np.floor(sy).astype(np.int64)
    sx1 = sx0 + 1
    sy1 = sy0 + 1

    fx = (sx - sx0).astype(np.float64)
    fy = (sy - sy0).astype(np.float64)

    # 边界检查
    valid = (sx0 >= 0) & (sy0 >= 0) & (sx1 < w) & (sy1 < h)

    sx0c = np.clip(sx0, 0, w - 1)
    sy0c = np.clip(sy0, 0, h - 1)
    sx1c = np.clip(sx1, 0, w - 1)
    sy1c = np.clip(sy1, 0, h - 1)

    for ch in range(c):
        plane = img[:, :, ch].astype(np.float64)
        val = (plane[sy0c, sx0c] * (1 - fx) * (1 - fy) +
               plane[sy0c, sx1c] * fx * (1 - fy) +
               plane[sy1c, sx0c] * (1 - fx) * fy +
               plane[sy1c, sx1c] * fx * fy)
        val[~valid] = 0
        result[:, :, ch] = np.clip(val, 0, 255).astype(img.dtype)

    if c == 1:
        return result[:, :, 0]
    return result


def apply_jpeg_compression(img, quality=70):
    """JPEG 压缩攻击"""
    pil_img = Image.fromarray(img)
    buf = io.BytesIO()
    pil_img.save(buf, format='JPEG', quality=quality)
    buf.seek(0)
    compressed = np.array(Image.open(buf))
    return compressed


def apply_gaussian_noise(img, sigma=5):
    """高斯噪声攻击"""
    noise = np.random.normal(0, sigma, img.shape)
    noisy = np.clip(img.astype(np.float64) + noise, 0, 255).astype(np.uint8)
    return noisy


def apply_brightness_contrast(img, brightness=20, contrast=1.2):
    """亮度/对比度变化"""
    result = img.astype(np.float64) * contrast + brightness
    return np.clip(result, 0, 255).astype(np.uint8)


def apply_gaussian_blur(img, sigma=1.0):
    """高斯模糊"""
    pil_img = Image.fromarray(img)
    blurred = pil_img.filter(ImageFilter.GaussianBlur(radius=sigma))
    return np.array(blurred)


def apply_scaling(img, scale=0.7):
    """缩放攻击"""
    pil_img = Image.fromarray(img)
    new_w = int(pil_img.width * scale)
    new_h = int(pil_img.height * scale)
    scaled = pil_img.resize((new_w, new_h), Image.BILINEAR)
    return np.array(scaled)


# ==================== 3. 自相关几何校正算法 ====================

def autocorrelation_2d_fft(block):
    """
    用 FFT 计算 2D 自相关函数（归一化）
    autocorr(τ) = IFFT(|FFT(block)|²)
    """
    f = fft2(block.astype(np.float64))
    power = np.abs(f) ** 2
    autocorr = np.real(ifft2(power))
    # 归一化
    if autocorr[0, 0] > 0:
        autocorr /= autocorr[0, 0]
    return autocorr


def find_peaks_2d(img, num_peaks=10, min_distance=20):
    """在 2D 图像中找局部极大值"""
    # 局部最大值滤波
    local_max = ndimage.maximum_filter(img, size=min_distance)
    peaks_mask = (img == local_max) & (img > 0.02)

    coords = np.argwhere(peaks_mask)  # (y, x)
    if len(coords) == 0:
        return []

    values = img[coords[:, 0], coords[:, 1]]
    order = np.argsort(-values)[:num_peaks]

    return [(int(coords[i][1]), int(coords[i][0]), float(values[i])) for i in order]


def extract_basis_vectors(vectors, expected_length, length_tolerance=0.5):
    """
    从周期向量候选中提取两个基向量
    expected_length: 期望的 tile 大小（像素）
    """
    if len(vectors) < 2:
        return None, None

    # 按向量长度排序
    vectors_with_len = []
    for v in vectors:
        length = np.sqrt(v[0] ** 2 + v[1] ** 2)
        # 过滤掉长度偏离期望太远的
        if expected_length * (1 - length_tolerance) < length < expected_length * (1 + length_tolerance):
            vectors_with_len.append((v, length))

    if len(vectors_with_len) < 2:
        # 放宽条件重试
        for v in vectors:
            length = np.sqrt(v[0] ** 2 + v[1] ** 2)
            if length > 20:  # 至少不是噪声
                vectors_with_len.append((v, length))

    if len(vectors_with_len) < 2:
        return None, None

    vectors_with_len.sort(key=lambda x: x[1])
    v1 = np.array(vectors_with_len[0][0], dtype=np.float64)

    # 找与 v1 最接近正交的向量
    best_v2 = None
    best_ortho_score = -1
    for v, l in vectors_with_len[1:]:
        v = np.array(v, dtype=np.float64)
        cross = abs(v1[0] * v[1] - v1[1] * v[0])
        norm_prod = np.linalg.norm(v1) * np.linalg.norm(v)
        if norm_prod > 0:
            sin_angle = cross / norm_prod
            if sin_angle > best_ortho_score:
                best_ortho_score = sin_angle
                best_v2 = v

    return v1, best_v2


def detect_local_period(block, expected_tile_size=TILE_SIZE):
    """
    检测一个图像块的局部 tile 周期向量
    返回两个基向量 v1, v2
    """
    if block.ndim == 3:
        block = np.mean(block, axis=2)

    h, w = block.shape

    # 计算自相关
    autocorr = autocorrelation_2d_fft(block)

    # fftshift 让零频在中心
    autocorr_shifted = fftshift(autocorr)
    cy, cx = h // 2, w // 2

    # 屏蔽中心（排除零延迟峰）和太远区域
    min_dist = int(expected_tile_size * 0.4)
    max_dist = int(expected_tile_size * 1.8)

    Y, X = np.ogrid[:h, :w]
    dist_sq = (X - cx) ** 2 + (Y - cy) ** 2
    mask = (dist_sq < min_dist ** 2) | (dist_sq > max_dist ** 2)
    autocorr_shifted[mask] = 0

    # 找峰值
    peaks = find_peaks_2d(autocorr_shifted, num_peaks=8, min_distance=int(expected_tile_size * 0.3))

    if len(peaks) < 2:
        return None, None, 0

    # 峰值转为向量（相对于中心）
    vectors = [(px - cx, py - cy) for (px, py, val) in peaks]
    peak_strength = peaks[0][2] if peaks else 0

    v1, v2 = extract_basis_vectors(vectors, expected_tile_size)
    return v1, v2, peak_strength


def correct_perspective_from_tiling(photo, tile_size=TILE_SIZE, block_size=512, step_ratio=0.5):
    """
    主校正算法：
    1. 分块检测局部周期向量
    2. 构建对应点对（变形后 vs 理想网格）
    3. 求单应性矩阵 H
    4. 校正全图
    """
    if photo.ndim == 3:
        gray = np.mean(photo, axis=2).astype(np.float64)
    else:
        gray = photo.astype(np.float64)

    h, w = gray.shape
    step = int(block_size * step_ratio)

    src_points = []
    dst_points = []

    block_count = 0
    valid_count = 0

    # 分块检测
    for by in range(0, h - block_size, step):
        for bx in range(0, w - block_size, step):
            block = gray[by:by + block_size, bx:bx + block_size]
            block_count += 1

            v1, v2, strength = detect_local_period(block, tile_size)

            if v1 is None or v2 is None:
                continue
            if strength < 0.03:
                continue

            valid_count += 1

            # 块中心
            center_x = bx + block_size / 2.0
            center_y = by + block_size / 2.0

            p0 = np.array([center_x, center_y])
            p1 = p0 + v1
            p2 = p0 + v2

            # 理想网格坐标（假设无变形时 tile 等间距排列）
            ideal_gx = round(center_x / tile_size) * tile_size
            ideal_gy = round(center_y / tile_size) * tile_size

            q0 = np.array([ideal_gx, ideal_gy], dtype=np.float64)
            q1 = q0 + np.array([tile_size, 0], dtype=np.float64)
            q2 = q0 + np.array([0, tile_size], dtype=np.float64)

            # 确定 v1, v2 哪个更接近水平/垂直
            if abs(v1[0]) > abs(v1[1]):
                # v1 更水平
                if v1[0] < 0:
                    v1 = -v1
                if v2[1] < 0:
                    v2 = -v2
                src_points.extend([p0, p0 + v1, p0 + v2])
                dst_points.extend([q0, q1, q2])
            else:
                # v1 更垂直
                if v2[0] < 0:
                    v2 = -v2
                if v1[1] < 0:
                    v1 = -v1
                src_points.extend([p0, p0 + v2, p0 + v1])
                dst_points.extend([q0, q1, q2])

    print(f"  分析了 {block_count} 个块, 有效 {valid_count} 个")

    if len(src_points) < 4:
        print("  警告: 有效点对不足，无法校正")
        return photo, np.eye(3), False

    src = np.array(src_points, dtype=np.float64)
    dst = np.array(dst_points, dtype=np.float64)

    # RANSAC 求单应性矩阵
    H, inlier_mask = ransac_homography(src, dst, threshold=10.0, max_iters=2000)

    if H is None:
        print("  警告: RANSAC 求解失败")
        return photo, np.eye(3), False

    inlier_ratio = np.sum(inlier_mask) / len(inlier_mask) if inlier_mask is not None else 0
    print(f"  RANSAC 内点率: {inlier_ratio:.1%} ({np.sum(inlier_mask)}/{len(inlier_mask)})")

    # 计算输出范围
    img_corners = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float64)
    transformed = perspective_transform_points(img_corners, H)

    x_min = max(0, transformed[:, 0].min())
    y_min = max(0, transformed[:, 1].min())
    x_max = transformed[:, 0].max()
    y_max = transformed[:, 1].max()

    # 限制输出大小合理范围
    out_w = min(int(x_max - x_min), w * 2)
    out_h = min(int(y_max - y_min), h * 2)

    # 加平移使坐标为正
    T = np.array([[1, 0, -x_min], [0, 1, -y_min], [0, 0, 1]], dtype=np.float64)
    H_adj = T @ H

    corrected = warp_perspective(photo, H_adj, out_w, out_h)
    return corrected, H_adj, True


def perspective_transform_points(points, H):
    """用 H 变换一组 2D 点"""
    N = len(points)
    ones = np.ones((N, 1))
    pts_h = np.hstack([points, ones])  # (N, 3)
    transformed = (H @ pts_h.T).T  # (N, 3)
    transformed /= transformed[:, 2:3]
    return transformed[:, :2]


def ransac_homography(src, dst, threshold=5.0, max_iters=1000):
    """
    RANSAC 求单应性矩阵
    src, dst: (N, 2) 对应点
    """
    N = len(src)
    if N < 4:
        return None, None

    best_H = None
    best_inliers = 0
    best_mask = None

    for _ in range(max_iters):
        # 随机选 4 对点
        idx = np.random.choice(N, 4, replace=False)
        s = src[idx].astype(np.float32)
        d = dst[idx].astype(np.float32)

        # 求 H
        try:
            H = compute_perspective_matrix(s, d)
        except Exception:
            continue

        # 计算所有点的重投影误差
        transformed = perspective_transform_points(src, H)
        errors = np.sqrt(np.sum((transformed - dst) ** 2, axis=1))
        inlier_mask = errors < threshold
        num_inliers = np.sum(inlier_mask)

        if num_inliers > best_inliers:
            best_inliers = num_inliers
            best_mask = inlier_mask
            best_H = H

    # 用所有内点重新拟合
    if best_H is not None and best_inliers >= 4:
        inlier_src = src[best_mask]
        inlier_dst = dst[best_mask]
        if len(inlier_src) >= 4:
            try:
                # 用最小二乘拟合所有内点
                best_H = fit_homography_lstsq(inlier_src, inlier_dst)
            except Exception:
                pass

    return best_H, best_mask


def fit_homography_lstsq(src, dst):
    """用所有点对最小二乘拟合单应性矩阵"""
    N = len(src)
    A = []
    for i in range(N):
        x, y = src[i]
        u, v = dst[i]
        A.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
        A.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
    A = np.array(A, dtype=np.float64)
    _, _, Vt = np.linalg.svd(A)
    H = Vt[-1].reshape(3, 3)
    H /= H[2, 2]
    return H


# ==================== 4. 水印提取与评估 ====================

def extract_watermark_tile(corrected_img, tile_size=TILE_SIZE, original_tile=None):
    """
    从校正后的图像中提取水印 tile
    通过多 tile 叠加平均来增强信噪比
    """
    if corrected_img.ndim == 3:
        gray = np.mean(corrected_img, axis=2).astype(np.float64)
    else:
        gray = corrected_img.astype(np.float64)

    h, w = gray.shape
    rows = h // tile_size
    cols = w // tile_size

    if rows < 1 or cols < 1:
        return None, 0.0

    # 提取所有完整 tile 并叠加
    tile_sum = np.zeros((tile_size, tile_size), dtype=np.float64)
    count = 0

    for r in range(rows):
        for c in range(cols):
            y0 = r * tile_size
            x0 = c * tile_size
            tile_block = gray[y0:y0 + tile_size, x0:x0 + tile_size]
            if tile_block.shape == (tile_size, tile_size):
                tile_sum += tile_block
                count += 1

    if count == 0:
        return None, 0.0

    tile_avg = tile_sum / count

    # 二值化提取
    median_val = np.median(tile_avg)
    extracted = (tile_avg > median_val).astype(np.uint8) * 255

    # 计算与原始 tile 的相关性
    if original_tile is not None:
        nc = normalized_correlation(original_tile, extracted)
    else:
        nc = 0.0

    return extracted, nc


def normalized_correlation(img1, img2):
    """归一化互相关 (NCC)，范围 [-1, 1]"""
    if img1.shape != img2.shape:
        # 裁剪到相同大小
        min_h = min(img1.shape[0], img2.shape[0])
        min_w = min(img1.shape[1], img2.shape[1])
        img1 = img1[:min_h, :min_w]
        img2 = img2[:min_h, :min_w]

    a = img1.astype(np.float64).flatten()
    b = img2.astype(np.float64).flatten()
    a -= a.mean()
    b -= b.mean()

    denom = np.sqrt(np.sum(a ** 2) * np.sum(b ** 2))
    if denom < 1e-10:
        return 0.0
    return float(np.sum(a * b) / denom)


def bit_accuracy(original_tile, extracted_tile):
    """计算比特准确率"""
    if original_tile.shape != extracted_tile.shape:
        min_h = min(original_tile.shape[0], extracted_tile.shape[0])
        min_w = min(original_tile.shape[1], extracted_tile.shape[1])
        original_tile = original_tile[:min_h, :min_w]
        extracted_tile = extracted_tile[:min_h, :min_w]

    orig_bits = (original_tile > 127).astype(np.uint8)
    extr_bits = (extracted_tile > 127).astype(np.uint8)
    return float(np.mean(orig_bits == extr_bits))


# ==================== 5. 完整测试流程 ====================

def run_single_test(name, attacked_img, original_tile, tile_size=TILE_SIZE):
    """运行单个测试: 校正 → 提取 → 评估"""
    print(f"\n{'=' * 60}")
    print(f"测试场景: {name}")
    print(f"{'=' * 60}")
    print(f"  输入图像大小: {attacked_img.shape}")

    t0 = time.time()

    # 几何校正
    corrected, H, success = correct_perspective_from_tiling(
        attacked_img, tile_size=tile_size, block_size=512, step_ratio=0.5
    )
    t_correct = time.time() - t0

    if not success:
        print(f"  校正失败!")
        print(f"  耗时: {t_correct:.2f}s")
        # 尝试直接在未校正图上提取
        extracted, nc = extract_watermark_tile(attacked_img, tile_size, original_tile)
        if extracted is not None:
            ba = bit_accuracy(original_tile, extracted)
            print(f"  [未校正] NCC={nc:.4f}, 比特准确率={ba:.2%}")
        return {"name": name, "success": False, "ncc": 0, "bit_acc": 0, "time": t_correct}

    print(f"  校正后大小: {corrected.shape}")

    # 水印提取
    extracted, nc = extract_watermark_tile(corrected, tile_size, original_tile)

    if extracted is None:
        print(f"  水印提取失败!")
        return {"name": name, "success": True, "ncc": 0, "bit_acc": 0, "time": t_correct}

    ba = bit_accuracy(original_tile, extracted)
    t_total = time.time() - t0

    print(f"  归一化互相关 (NCC): {nc:.4f}")
    print(f"  比特准确率: {ba:.2%}")
    print(f"  总耗时: {t_total:.2f}s")

    status = "✓ 通过" if ba > 0.7 else ("△ 部分" if ba > 0.55 else "✗ 失败")
    print(f"  结果: {status}")

    return {"name": name, "success": True, "ncc": nc, "bit_acc": ba, "time": t_total}


def run_baseline_test(watermarked_img, original_tile):
    """基线测试: 无攻击，直接提取"""
    print(f"\n{'=' * 60}")
    print(f"基线测试: 无攻击直接提取")
    print(f"{'=' * 60}")
    extracted, nc = extract_watermark_tile(watermarked_img, TILE_SIZE, original_tile)
    if extracted is not None:
        ba = bit_accuracy(original_tile, extracted)
        print(f"  NCC={nc:.4f}, 比特准确率={ba:.2%}")
        return {"name": "baseline", "ncc": nc, "bit_acc": ba}
    return {"name": "baseline", "ncc": 0, "bit_acc": 0}


def main():
    print("=" * 70)
    print("  屏摄图片几何校正算法 - 基于 Tile 平铺自相关")
    print("  鲁棒性测试套件")
    print("=" * 70)

    # 1. 生成水印 tile
    print("\n[1] 生成 267x267 二值水印 tile...")
    tile = generate_binary_tile(TILE_SIZE, seed=12345)
    print(f"  tile 大小: {tile.shape}, 值域: [{tile.min()}, {tile.max()}]")
    print(f"  白色像素占比: {np.mean(tile > 127):.1%}")

    # 2. 平铺水印
    print("\n[2] 平铺水印到屏幕 ({SCREEN_W}x{SCREEN_H})...")
    watermark_layer = tile_watermark_on_screen(tile)
    print(f"  水印层大小: {watermark_layer.shape}")

    # 3. 生成屏幕内容
    print("\n[3] 生成模拟屏幕内容...")
    content = generate_screen_content()
    print(f"  内容图大小: {content.shape}")

    # 4. 嵌入水印
    print("\n[4] 嵌入水印 (alpha={WATERMARK_ALPHA})...")
    watermarked = embed_watermark(content, watermark_layer, WATERMARK_ALPHA)
    diff = np.abs(watermarked.astype(np.float64) - content.astype(np.float64))
    print(f"  嵌入后最大像素差: {diff.max():.1f}")
    print(f"  嵌入后平均像素差: {diff.mean():.3f}")

    # 5. 基线测试
    baseline = run_baseline_test(watermarked, tile)

    # 6. 攻击场景测试
    results = [baseline]

    # ---- 场景 1: 轻微透视变形 ----
    attacked, _, _, _ = apply_perspective_transform(watermarked, "light")
    results.append(run_single_test("轻微透视变形 (3%)", attacked, tile))

    # ---- 场景 2: 中等透视变形 ----
    attacked, _, _, _ = apply_perspective_transform(watermarked, "medium")
    results.append(run_single_test("中等透视变形 (8%)", attacked, tile))

    # ---- 场景 3: 严重透视变形 ----
    attacked, _, _, _ = apply_perspective_transform(watermarked, "heavy")
    results.append(run_single_test("严重透视变形 (15%)", attacked, tile))

    # ---- 场景 4: JPEG 压缩 Q=90 ----
    attacked = apply_jpeg_compression(watermarked, quality=90)
    results.append(run_single_test("JPEG压缩 Q=90", attacked, tile))

    # ---- 场景 5: JPEG 压缩 Q=50 ----
    attacked = apply_jpeg_compression(watermarked, quality=50)
    results.append(run_single_test("JPEG压缩 Q=50", attacked, tile))

    # ---- 场景 6: 高斯噪声 σ=5 ----
    attacked = apply_gaussian_noise(watermarked, sigma=5)
    results.append(run_single_test("高斯噪声 σ=5", attacked, tile))

    # ---- 场景 7: 高斯噪声 σ=15 ----
    attacked = apply_gaussian_noise(watermarked, sigma=15)
    results.append(run_single_test("高斯噪声 σ=15", attacked, tile))

    # ---- 场景 8: 亮度对比度变化 ----
    attacked = apply_brightness_contrast(watermarked, brightness=30, contrast=1.3)
    results.append(run_single_test("亮度+30 对比度×1.3", attacked, tile))

    # ---- 场景 9: 高斯模糊 ----
    attacked = apply_gaussian_blur(watermarked, sigma=1.5)
    results.append(run_single_test("高斯模糊 σ=1.5", attacked, tile))

    # ---- 场景 10: 缩放 70% ----
    attacked = apply_scaling(watermarked, scale=0.7)
    results.append(run_single_test("缩放 70%", attacked, tile,
                                    tile_size=int(TILE_SIZE * 0.7)))

    # ---- 场景 11: 透视 + JPEG 组合 ----
    attacked, _, _, _ = apply_perspective_transform(watermarked, "medium")
    attacked = apply_jpeg_compression(attacked, quality=70)
    results.append(run_single_test("透视(8%) + JPEG Q=70", attacked, tile))

    # ---- 场景 12: 透视 + 噪声 + JPEG 组合 ----
    attacked, _, _, _ = apply_perspective_transform(watermarked, "medium")
    attacked = apply_gaussian_noise(attacked, sigma=5)
    attacked = apply_jpeg_compression(attacked, quality=70)
    results.append(run_single_test("透视(8%) + 噪声σ=5 + JPEG Q=70", attacked, tile))

    # ---- 场景 13: 透视 + 亮度 + JPEG (模拟真实屏摄) ----
    attacked, _, _, _ = apply_perspective_transform(watermarked, "light")
    attacked = apply_brightness_contrast(attacked, brightness=15, contrast=1.1)
    attacked = apply_gaussian_blur(attacked, sigma=0.8)
    attacked = apply_jpeg_compression(attacked, quality=80)
    results.append(run_single_test("模拟真实屏摄 (轻透视+亮度+模糊+JPEG)", attacked, tile))

    # 7. 汇总报告
    print("\n")
    print("=" * 70)
    print("  鲁棒性测试汇总报告")
    print("=" * 70)
    print(f"{'场景':<45} {'NCC':>8} {'比特准确率':>10} {'结果':>8}")
    print("-" * 70)
    for r in results:
        ncc = r.get('ncc', 0)
        ba = r.get('bit_acc', 0)
        if ba > 0.7:
            status = "✓"
        elif ba > 0.55:
            status = "△"
        else:
            status = "✗"
        t = r.get('time', 0)
        time_str = f"{t:.1f}s" if t > 0 else "-"
        print(f"  {r['name']:<43} {ncc:>7.4f} {ba:>9.2%}  {status:>4}  {time_str:>6}")

    print("-" * 70)

    # 统计
    test_results = [r for r in results if r['name'] != 'baseline']
    passed = sum(1 for r in test_results if r.get('bit_acc', 0) > 0.7)
    partial = sum(1 for r in test_results if 0.55 < r.get('bit_acc', 0) <= 0.7)
    failed = sum(1 for r in test_results if r.get('bit_acc', 0) <= 0.55)
    print(f"  通过: {passed}  部分通过: {partial}  失败: {failed}  总计: {len(test_results)}")
    print(f"  平均比特准确率: {np.mean([r.get('bit_acc', 0) for r in test_results]):.2%}")
    print("=" * 70)


if __name__ == "__main__":
    main()
