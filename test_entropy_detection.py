"""
香农信息熵检测加密/编码数据 - 验证程序
自动生成多种类型测试数据，验证熵值阈值判断的合理性
"""

import os
import sys
import base64
import gzip
import json
import hashlib
import struct
import tempfile
import shutil
from math import log2
from collections import Counter
from pathlib import Path

# 修复 Windows 终端编码
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# ==================== 核心检测函数 ====================

def calc_shannon_entropy(data: bytes) -> float:
    """计算字节级香农信息熵，范围 0.0 ~ 8.0"""
    if not data:
        return 0.0
    freq = Counter(data)
    length = len(data)
    return -sum((count / length) * log2(count / length) for count in freq.values())


def detect_encrypted_or_encoded(data: bytes, filename: str = "") -> dict:
    """综合判断数据是否为加密/编码内容"""
    entropy = calc_shannon_entropy(data)

    result = {
        "entropy": round(entropy, 4),
        "verdict": "normal",
        "confidence": "low",
        "detail": ""
    }

    # 高熵：加密或压缩数据
    if entropy >= 7.5:
        result["verdict"] = "encrypted_or_compressed"
        result["confidence"] = "high"
        result["detail"] = "熵值极高，数据接近随机分布，高度疑似加密/压缩"

    # 中高熵：可能是 Base64 或其他编码
    elif entropy >= 5.8:
        text = data.decode("utf-8", errors="ignore")
        base64_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\n\r")
        base64_ratio = sum(1 for c in text if c in base64_chars) / max(len(text), 1)

        if base64_ratio > 0.95:
            result["verdict"] = "base64_encoded"
            result["confidence"] = "high"
            result["detail"] = f"Base64字符占比 {base64_ratio:.1%}"
        else:
            hex_chars = set("0123456789abcdefABCDEF \n\r")
            hex_ratio = sum(1 for c in text if c in hex_chars) / max(len(text), 1)
            if hex_ratio > 0.95:
                result["verdict"] = "hex_encoded"
                result["confidence"] = "high"
                result["detail"] = f"Hex字符占比 {hex_ratio:.1%}"
            else:
                result["verdict"] = "possibly_encoded"
                result["confidence"] = "medium"
                result["detail"] = "可能是编码数据或高熵文本"

    # 正常范围
    elif entropy >= 3.5:
        result["verdict"] = "normal"
        result["detail"] = "符合正常文本/代码特征"

    # 低熵
    else:
        result["verdict"] = "low_entropy"
        result["detail"] = "重复性高或内容简单"

    return result


# ==================== 测试数据生成 ====================

def generate_test_files(test_dir: str) -> list:
    """生成各种类型的测试文件，返回 (文件名, 预期类别, 描述) 列表"""
    os.makedirs(test_dir, exist_ok=True)
    test_cases = []

    # ---------- 1. 正常文本类 ----------

    # 英文文本
    english_text = (
        "The quick brown fox jumps over the lazy dog. "
        "Data Loss Prevention (DLP) is a set of tools and processes used to ensure "
        "that sensitive data is not lost, misused, or accessed by unauthorized users. "
        "DLP software classifies regulated, confidential and business critical data "
        "and identifies violations of policies defined by organizations or within a "
        "predefined policy pack. Once those violations are identified, DLP enforces "
        "remediation with alerts, encryption, and other protective actions to prevent "
        "end users from accidentally or maliciously sharing data that could put the "
        "organization at risk. This is a normal English text that should have moderate "
        "entropy values around 4.0 to 5.0 bits per byte."
    ) * 5
    _write(test_dir, "01_english_text.txt", english_text.encode("utf-8"))
    test_cases.append(("01_english_text.txt", "normal", "英文自然语言"))

    # 中文文本
    chinese_text = (
        "数据防泄漏（DLP）是一套用于确保敏感数据不会丢失、滥用或被未授权用户访问的工具和流程。"
        "DLP软件对受监管的、机密的和业务关键数据进行分类，并识别违反组织定义的策略或预定义策略包的行为。"
        "一旦发现这些违规行为，DLP就会通过警报、加密和其他保护措施进行补救，"
        "以防止最终用户意外或恶意共享可能使组织面临风险的数据。"
        "香农信息熵是信息论中的核心概念，用于度量信息的不确定性。"
        "在数据安全领域，我们可以利用信息熵来检测数据是否经过加密或编码处理。"
    ) * 3
    _write(test_dir, "02_chinese_text.txt", chinese_text.encode("utf-8"))
    test_cases.append(("02_chinese_text.txt", "normal", "中文自然语言(UTF-8)"))

    # Python 源代码
    python_code = '''
import os
import sys
from collections import Counter
from math import log2

class DataAnalyzer:
    """数据分析器"""
    def __init__(self, filepath):
        self.filepath = filepath
        self.data = None

    def load(self):
        with open(self.filepath, "rb") as f:
            self.data = f.read()
        return self

    def compute_entropy(self):
        if not self.data:
            return 0.0
        freq = Counter(self.data)
        length = len(self.data)
        entropy = -sum((c/length) * log2(c/length) for c in freq.values())
        return entropy

    def analyze(self):
        entropy = self.compute_entropy()
        if entropy > 7.5:
            return "high_entropy"
        elif entropy > 5.8:
            return "medium_entropy"
        else:
            return "normal"

if __name__ == "__main__":
    analyzer = DataAnalyzer(sys.argv[1])
    result = analyzer.load().analyze()
    print(f"Result: {result}")
''' * 3
    _write(test_dir, "03_python_code.py", python_code.encode("utf-8"))
    test_cases.append(("03_python_code.py", "normal", "Python源代码"))

    # JSON 配置
    json_data = json.dumps({
        "server": {
            "host": "192.168.1.100",
            "port": 8080,
            "workers": 4,
            "debug": False,
            "log_level": "INFO"
        },
        "database": {
            "engine": "postgresql",
            "host": "db.example.com",
            "port": 5432,
            "name": "dlp_system",
            "user": "admin",
            "pool_size": 10
        },
        "redis": {
            "host": "redis.example.com",
            "port": 6379,
            "db": 0
        },
        "features": ["content_inspection", "fingerprinting", "ocr", "nlp"],
        "rules": [
            {"id": 1, "name": "credit_card", "pattern": r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"},
            {"id": 2, "name": "phone_number", "pattern": r"\b1[3-9]\d{9}\b"},
            {"id": 3, "name": "id_card", "pattern": r"\b\d{17}[\dXx]\b"}
        ]
    }, indent=2, ensure_ascii=False) * 3
    _write(test_dir, "04_json_config.json", json_data.encode("utf-8"))
    test_cases.append(("04_json_config.json", "normal", "JSON配置文件"))

    # CSV 数据
    csv_lines = ["name,age,email,department,salary\n"]
    names = ["张三", "李四", "王五", "赵六", "钱七", "孙八", "周九", "吴十"]
    depts = ["技术部", "市场部", "财务部", "人事部"]
    for i in range(200):
        name = names[i % len(names)]
        csv_lines.append(f"{name},{25 + i % 20},{name}_{i}@company.com,{depts[i % len(depts)]},{8000 + i * 100}\n")
    _write(test_dir, "05_csv_data.csv", "".join(csv_lines).encode("utf-8"))
    test_cases.append(("05_csv_data.csv", "normal", "CSV表格数据"))

    # ---------- 2. 编码类 ----------

    # Base64 编码的文本
    secret_text = ("这是一份绝密文件，包含公司核心技术方案和客户隐私数据。" * 20).encode("utf-8")
    b64_encoded = base64.b64encode(secret_text)
    _write(test_dir, "06_base64_text.txt", b64_encoded)
    test_cases.append(("06_base64_text.txt", "base64_encoded", "Base64编码的中文文本"))

    # Base64 编码的二进制数据
    binary_data = os.urandom(2048)
    b64_binary = base64.b64encode(binary_data)
    _write(test_dir, "07_base64_binary.txt", b64_binary)
    test_cases.append(("07_base64_binary.txt", "base64_encoded", "Base64编码的随机二进制"))

    # Hex 编码
    hex_data = binary_data[:1024].hex()
    _write(test_dir, "08_hex_encoded.txt", hex_data.encode("utf-8"))
    test_cases.append(("08_hex_encoded.txt", "hex_encoded", "Hex编码的二进制数据"))

    # Base64 编码嵌入普通文本（模拟隐蔽泄露）
    mixed_text = f"""
Subject: 项目周报
From: employee@company.com
Date: 2025-01-15

本周工作总结：
1. 完成了DLP系统的设计文档
2. 附件数据如下：

{base64.b64encode(("机密：2025年Q1财务报表，总营收12.5亿，净利润3.2亿，研发投入2.1亿" * 10).encode("utf-8")).decode("utf-8")}

以上，请查收。
"""
    _write(test_dir, "09_mixed_base64.txt", mixed_text.encode("utf-8"))
    test_cases.append(("09_mixed_base64.txt", "possibly_encoded", "混合文本(含Base64片段)"))

    # ---------- 3. 加密/压缩类 ----------

    # AES 模拟加密数据（用 os.urandom 模拟，真实 AES 密文统计特性与随机数一致）
    aes_like_data = os.urandom(4096)
    _write(test_dir, "10_encrypted_data.bin", aes_like_data)
    test_cases.append(("10_encrypted_data.bin", "encrypted_or_compressed", "模拟AES加密数据(随机字节)"))

    # Gzip 压缩数据
    original_text = ("这是一段会被压缩的文本内容，压缩后的数据应该具有高熵值。" * 100).encode("utf-8")
    gzipped = gzip.compress(original_text)
    _write(test_dir, "11_gzipped_data.gz", gzipped)
    test_cases.append(("11_gzipped_data.gz", "encrypted_or_compressed", "Gzip压缩数据"))

    # 伪装成 txt 的加密数据（高风险场景）
    fake_txt_encrypted = os.urandom(4096)
    _write(test_dir, "12_fake_txt_encrypted.txt", fake_txt_encrypted)
    test_cases.append(("12_fake_txt_encrypted.txt", "encrypted_or_compressed", "伪装成txt的加密数据"))

    # 伪装成 csv 的加密数据
    fake_csv_encrypted = os.urandom(4096)
    _write(test_dir, "13_fake_csv_encrypted.csv", fake_csv_encrypted)
    test_cases.append(("13_fake_csv_encrypted.csv", "encrypted_or_compressed", "伪装成csv的加密数据"))

    # ---------- 4. 低熵类 ----------

    # 全重复字符
    repeated = b"AAAAAAAAAA" * 500
    _write(test_dir, "14_repeated_chars.txt", repeated)
    test_cases.append(("14_repeated_chars.txt", "low_entropy", "全重复字符"))

    # 少量字符重复
    few_chars = (b"ABCD" * 1000)
    _write(test_dir, "15_few_chars.txt", few_chars)
    test_cases.append(("15_few_chars.txt", "low_entropy", "少量字符循环重复"))

    # 空白文件（大量空格和换行）
    whitespace = (b"    \n" * 1000)
    _write(test_dir, "16_whitespace.txt", whitespace)
    test_cases.append(("16_whitespace.txt", "low_entropy", "空白字符文件"))

    # ---------- 5. 边界/特殊 ----------

    # 密码列表（中等熵值，但有安全意义）
    passwords = "\n".join([
        f"user{i:04d}:P@ssw0rd_{hashlib.md5(str(i).encode()).hexdigest()[:8]}"
        for i in range(500)
    ])
    _write(test_dir, "17_password_list.txt", passwords.encode("utf-8"))
    test_cases.append(("17_password_list.txt", "normal", "密码列表（结构化文本）"))

    # 混淆的 JavaScript 代码
    obfuscated_js = "var _0x" + "".join(
        f"={hex(b)}" for b in os.urandom(200)
    ) + ";function _0x" + "abcdef" * 50 + "(a,b){return a^b;}" * 20
    _write(test_dir, "18_obfuscated_js.js", obfuscated_js.encode("utf-8"))
    test_cases.append(("18_obfuscated_js.js", "possibly_encoded", "混淆的JavaScript代码"))

    # SHA256 哈希值列表
    hash_list = "\n".join([
        hashlib.sha256(f"file_{i}".encode()).hexdigest()
        for i in range(200)
    ])
    _write(test_dir, "19_hash_list.txt", hash_list.encode("utf-8"))
    test_cases.append(("19_hash_list.txt", "hex_encoded", "SHA256哈希值列表"))

    # 二进制可执行文件头 + 正常内容（模拟 PE 文件片段）
    pe_header = b"MZ" + os.urandom(256) + b"\x00" * 256 + b"This program cannot be run in DOS mode" + os.urandom(512)
    _write(test_dir, "20_binary_with_header.bin", pe_header)
    test_cases.append(("20_binary_with_header.bin", "encrypted_or_compressed", "二进制文件(含PE头)"))

    return test_cases


def _write(test_dir, filename, data):
    with open(os.path.join(test_dir, filename), "wb") as f:
        f.write(data)


# ==================== 测试执行 ====================

def run_tests():
    test_dir = os.path.join(tempfile.gettempdir(), "entropy_test_files")

    print("=" * 90)
    print("  香农信息熵检测加密/编码数据 - 验证测试")
    print("=" * 90)
    print(f"\n测试文件目录: {test_dir}\n")

    # 生成测试文件
    test_cases = generate_test_files(test_dir)

    # 统计
    total = len(test_cases)
    correct = 0
    results = []

    print(f"{'序号':<4} {'文件名':<32} {'大小':>8} {'熵值':>7} {'预期判断':<26} {'实际判断':<26} {'结果':<4}")
    print("-" * 115)

    for i, (filename, expected, desc) in enumerate(test_cases, 1):
        filepath = os.path.join(test_dir, filename)
        with open(filepath, "rb") as f:
            data = f.read()

        size = len(data)
        result = detect_encrypted_or_encoded(data, filename)
        actual = result["verdict"]

        # 判断是否匹配（possibly_encoded 可匹配多种编码类型）
        match = False
        if expected == actual:
            match = True
        elif expected == "possibly_encoded" and actual in ("base64_encoded", "hex_encoded", "possibly_encoded", "normal"):
            match = True
        elif expected in ("base64_encoded", "hex_encoded") and actual == "possibly_encoded":
            match = True  # 宽松匹配

        if match:
            correct += 1
            status = "✓"
        else:
            status = "✗"

        size_str = f"{size:,}B"
        print(f"{i:<4} {filename:<32} {size_str:>8} {result['entropy']:>7.4f} {expected:<26} {actual:<26} {status}")
        results.append((filename, desc, expected, actual, result["entropy"], match, result["detail"]))

    # ---- 汇总 ----
    print("-" * 115)
    accuracy = correct / total * 100
    print(f"\n总计: {total} 项 | 匹配: {correct} 项 | 准确率: {accuracy:.1f}%\n")

    # ---- 按类别统计熵值分布 ----
    print("=" * 90)
    print("  各类别熵值分布统计")
    print("=" * 90)

    categories = {}
    for filename, desc, expected, actual, entropy, match, detail in results:
        cat = expected
        if cat not in categories:
            categories[cat] = []
        categories[cat].append((filename, desc, entropy, match))

    for cat, items in categories.items():
        entropies = [e for _, _, e, _ in items]
        avg_e = sum(entropies) / len(entropies)
        min_e = min(entropies)
        max_e = max(entropies)
        correct_in_cat = sum(1 for _, _, _, m in items if m)

        print(f"\n【{cat}】 ({len(items)} 项, 匹配 {correct_in_cat}/{len(items)})")
        print(f"  熵值范围: {min_e:.4f} ~ {max_e:.4f}, 平均: {avg_e:.4f}")

        for fname, desc, ent, match in items:
            bar = "█" * int(ent * 5) + "░" * (40 - int(ent * 5))
            mark = "✓" if match else "✗"
            print(f"  {mark} {desc:<24} {ent:.4f} |{bar}|")

    # ---- 阈值有效性分析 ----
    print("\n" + "=" * 90)
    print("  阈值有效性分析")
    print("=" * 90)

    threshold_high = 7.5
    threshold_mid = 5.8
    threshold_low = 3.5

    print(f"\n当前阈值设置:")
    print(f"  高熵(加密/压缩): >= {threshold_high}")
    print(f"  中高熵(编码):    >= {threshold_mid}")
    print(f"  正常文本:        >= {threshold_low}")
    print(f"  低熵:            <  {threshold_low}")

    # 检查阈值是否有交叉误判
    normal_items = [(f, d, e) for f, d, exp, _, e, _, _ in results if exp == "normal"]
    encoded_items = [(f, d, e) for f, d, exp, _, e, _, _ in results if exp in ("base64_encoded", "hex_encoded", "possibly_encoded")]
    encrypted_items = [(f, d, e) for f, d, exp, _, e, _, _ in results if exp == "encrypted_or_compressed"]

    if normal_items:
        normal_max = max(e for _, _, e in normal_items)
        print(f"\n  正常文本最大熵值: {normal_max:.4f}")
        if normal_max >= threshold_mid:
            print(f"  ⚠ 警告: 正常文本熵值 {normal_max:.4f} 超过中高熵阈值 {threshold_mid}，可能误报")
        else:
            gap = threshold_mid - normal_max
            print(f"  ✓ 安全间隔: {gap:.4f} (距离中高熵阈值)")

    if encoded_items:
        encoded_min = min(e for _, _, e in encoded_items)
        encoded_max = max(e for _, _, e in encoded_items)
        print(f"\n  编码数据熵值范围: {encoded_min:.4f} ~ {encoded_max:.4f}")

    if encrypted_items:
        encrypted_min = min(e for _, _, e in encrypted_items)
        print(f"\n  加密/压缩数据最小熵值: {encrypted_min:.4f}")
        if encrypted_min < threshold_high:
            print(f"  ⚠ 警告: 加密数据熵值 {encrypted_min:.4f} 低于高熵阈值 {threshold_high}，可能漏报")
        else:
            gap = encrypted_min - threshold_high
            print(f"  ✓ 安全间隔: {gap:.4f} (高于高熵阈值)")

    # ---- 误判分析 ----
    mismatches = [(f, d, exp, act, e, det) for f, d, exp, act, e, m, det in results if not m]
    if mismatches:
        print(f"\n{'=' * 90}")
        print(f"  误判详情 ({len(mismatches)} 项)")
        print(f"{'=' * 90}")
        for fname, desc, expected, actual, entropy, detail in mismatches:
            print(f"\n  文件: {fname}")
            print(f"  描述: {desc}")
            print(f"  熵值: {entropy:.4f}")
            print(f"  预期: {expected}")
            print(f"  实际: {actual}")
            print(f"  详情: {detail}")
    else:
        print(f"\n✓ 所有测试项均匹配预期，无误判！")

    # 清理
    print(f"\n{'=' * 90}")
    print(f"测试完成。测试文件保留在: {test_dir}")
    print(f"如需清理，请手动删除该目录。")

    return accuracy


if __name__ == "__main__":
    accuracy = run_tests()
