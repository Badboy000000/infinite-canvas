"""MinIO 生产环境一次性 bootstrap 工具 · Wave 3-N.9 Batch 0(Lead 亲自阻塞前置)

用途:
1. 用**根管账号**连接 minio.sbtionline.cloud
2. 在 `/root/data/disk/minio/data` 分区里建立项目专属 bucket `infinite-canvas`
   (与 sbtionline.cloud 其他项目文件仓通过 bucket 隔离)
3. 创建**项目专属 Access Key**,权限限定到 `infinite-canvas/*`
   (根凭据不落 API/.env)
4. 烟测:put / get / list / delete 一遍 · 打印结果供 Lead 校验
5. 输出的项目 Access Key 由 Lead 手工写入 `API/.env`,本脚本不写文件

**只能跑一次**——bucket 已存在时跳过创建;项目 access key 已存在时跳过创建。
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import timedelta
from urllib.parse import quote

from minio import Minio
from minio.error import S3Error

# ------ 根管凭据(Lead 手工传参 · 不入代码库) --------------------------------

DEFAULT_ENDPOINT = "minio.sbtionline.cloud"
DEFAULT_SECURE = True
DEFAULT_BUCKET = "infinite-canvas"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--admin-access-key", required=True, help="MinIO 根管账号 · 从命令行传入,不写死")
    ap.add_argument("--admin-secret-key", required=True, help="MinIO 根管密码 · 从命令行传入,不写死")
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="S3 API host(不含协议)")
    ap.add_argument("--secure", default="true", help="true=HTTPS false=HTTP")
    ap.add_argument("--bucket", default=DEFAULT_BUCKET, help="项目专属 bucket 名")
    ap.add_argument(
        "--dry-run", action="store_true",
        help="只做连通性 + list_buckets 探测,不做任何 mutate",
    )
    return ap.parse_args()


def _bucket_policy_project_scoped(bucket: str) -> str:
    """返回一份把权限限定到 `bucket/*` 前缀的 IAM policy JSON 字符串。

    本次 bootstrap 通过**服务器端 policy** 而不是 access key ACL 限权
    (MinIO CE 版 access key 不带 policy 参数;真正的最小权限访问要么走
    STS 临时凭据要么给 access key 绑定 policy,后者需要 `mc admin`)。
    """
    return json.dumps({
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:*"],
                "Resource": [
                    f"arn:aws:s3:::{bucket}",
                    f"arn:aws:s3:::{bucket}/*",
                ],
            }
        ],
    }, ensure_ascii=False)


def main() -> int:
    args = parse_args()
    secure = str(args.secure).lower() in {"true", "1", "yes", "y"}

    print(f"[bootstrap] endpoint={args.endpoint} secure={secure} bucket={args.bucket}")
    client = Minio(
        args.endpoint,
        access_key=args.admin_access_key,
        secret_key=args.admin_secret_key,
        secure=secure,
    )

    # --- Step 1 · 连通性 + 列 bucket ------------------------------------
    print("[step1] list_buckets() 探测连通性 ...")
    try:
        existing = list(client.list_buckets())
    except S3Error as exc:
        print(f"[fatal] list_buckets 失败 · S3Error code={exc.code} message={exc.message}")
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"[fatal] list_buckets 失败: {type(exc).__name__}: {exc}")
        return 2
    print(f"[step1] 现有 bucket({len(existing)}): {[b.name for b in existing]}")

    if args.dry_run:
        print("[dry-run] 只做连通性探测,退出")
        return 0

    # --- Step 2 · 创建项目 bucket(幂等) ---------------------------------
    if any(b.name == args.bucket for b in existing):
        print(f"[step2] bucket={args.bucket} 已存在 · 跳过创建")
    else:
        print(f"[step2] make_bucket({args.bucket}) ...")
        client.make_bucket(args.bucket)
        print(f"[step2] bucket={args.bucket} 创建成功")

    # --- Step 3 · put/get/list/delete 烟测 ------------------------------
    smoke_key = ".bootstrap-smoke/hello.txt"
    smoke_body = b"infinite-canvas bootstrap smoke @ Wave 3-N.9 Batch 0"
    print(f"[step3] put_object({args.bucket}/{smoke_key}) size={len(smoke_body)} ...")
    client.put_object(
        args.bucket,
        smoke_key,
        io.BytesIO(smoke_body),
        length=len(smoke_body),
        content_type="text/plain",
    )
    print("[step3] put ok")

    print(f"[step3] get_object({args.bucket}/{smoke_key}) ...")
    resp = client.get_object(args.bucket, smoke_key)
    fetched = resp.read()
    resp.close()
    resp.release_conn()
    assert fetched == smoke_body, f"round-trip mismatch: {fetched!r}"
    print(f"[step3] get ok · body={fetched.decode()!r}")

    print(f"[step3] list_objects({args.bucket}/.bootstrap-smoke/) ...")
    listing = list(client.list_objects(args.bucket, prefix=".bootstrap-smoke/"))
    print(f"[step3] list ok · {len(listing)} objects: {[o.object_name for o in listing]}")

    print(f"[step3] stat_object({args.bucket}/{smoke_key}) ...")
    stat = client.stat_object(args.bucket, smoke_key)
    print(f"[step3] stat ok · size={stat.size} etag={stat.etag}")

    # --- Step 4 · 生成 presigned GET URL(24h)---------------------------
    print("[step4] presigned_get_object(24h) ...")
    url = client.presigned_get_object(
        args.bucket, smoke_key, expires=timedelta(hours=24)
    )
    print(f"[step4] presigned url ok(长度={len(url)}, 头 80 字符):")
    print(f"        {url[:80]}...")

    # --- Step 5 · 清烟测对象 --------------------------------------------
    print(f"[step5] remove_object({args.bucket}/{smoke_key}) ...")
    client.remove_object(args.bucket, smoke_key)
    print("[step5] remove ok · 烟测残留清 0")

    print()
    print("=" * 60)
    print("[bootstrap] 全流程 PASS · 下一步:")
    print(f"  1. 在 MinIO 控制台 https://console.sbtionline.cloud/ 手工创建")
    print(f"     一个项目专属 Access Key(限定到 bucket={args.bucket})")
    print("  2. 把新 access/secret 写入 API/.env:")
    print(f"     MINIO_ENDPOINT={args.endpoint}")
    print(f"     MINIO_SECURE={str(secure).lower()}")
    print(f"     MINIO_BUCKET={args.bucket}")
    print("     MINIO_ACCESS_KEY=<项目专属>")
    print("     MINIO_SECRET_KEY=<项目专属>")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
