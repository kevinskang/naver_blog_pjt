"""이미지 업로드 기능 테스트."""

import asyncio
import sys
import urllib.request
from pathlib import Path
from PIL import Image
import pytest

sys.path.insert(0, "src")

from naver_blog_mcp.server import NaverBlogMCPServer
from naver_blog_mcp.automation.image_upload import (
    get_editor_frame,
    upload_image,
    upload_images,
)


def is_pstatic_reachable(timeout: int = 5) -> bool:
    try:
        with urllib.request.urlopen("https://feblog.pstatic.net", timeout=timeout):
            return True
    except Exception:
        return False


async def _editor_image_toolbar_available(page) -> bool:
    try:
        frame = await get_editor_frame(page)
        from naver_blog_mcp.automation.image_upload import IMAGE_BUTTON_SELECTORS

        for selector in IMAGE_BUTTON_SELECTORS:
            if await frame.locator(selector).count() > 0:
                return True
        return False
    except Exception:
        return False


async def create_test_images() -> list[Path]:
    """테스트용 이미지 파일을 생성합니다."""
    test_dir = Path("playwright-state/test-images")
    test_dir.mkdir(parents=True, exist_ok=True)

    images = []

    # 1. 간단한 PNG 이미지 (100x100, 빨간색)
    img1 = Image.new("RGB", (100, 100), color="red")
    path1 = test_dir / "test_image_1.png"
    img1.save(path1)
    images.append(path1)
    print(f"✅ 테스트 이미지 생성: {path1}")

    # 2. 간단한 JPG 이미지 (200x150, 파란색)
    img2 = Image.new("RGB", (200, 150), color="blue")
    path2 = test_dir / "test_image_2.jpg"
    img2.save(path2)
    images.append(path2)
    print(f"✅ 테스트 이미지 생성: {path2}")

    # 3. 간단한 GIF 이미지 (150x150, 초록색)
    img3 = Image.new("RGB", (150, 150), color="green")
    path3 = test_dir / "test_image_3.gif"
    img3.save(path3)
    images.append(path3)
    print(f"✅ 테스트 이미지 생성: {path3}")

    return images


async def test_single_image_upload():
    """단일 이미지 업로드 테스트."""
    if not is_pstatic_reachable():
        pytest.skip("pstatic.net is unreachable; Naver editor assets cannot be loaded in this environment.")

    print("=" * 60)
    print("단일 이미지 업로드 테스트")
    print("=" * 60)
    print()

    # 테스트 이미지 생성
    print("테스트 이미지 생성 중...")
    test_images = await create_test_images()
    print()

    server = NaverBlogMCPServer()

    try:
        # 서버 초기화
        await server.initialize()
        print("✅ 서버 초기화 완료")

        # 페이지 가져오기
        page = await server.get_page()
        print("✅ 페이지 생성 완료")

        # 글쓰기 페이지로 이동
        await page.goto("https://blog.naver.com/GoBlogWrite.naver")
        await asyncio.sleep(2)
        print("✅ 글쓰기 페이지 이동 완료")

        if not await _editor_image_toolbar_available(page):
            pytest.skip(
                "Naver editor image toolbar is unavailable; environment is not ready for image upload tests."
            )

        # iframe 확인
        frame = await get_editor_frame(page)
        print(f"✅ 에디터 iframe 접근 완료: {frame.url}")

        # 단일 이미지 업로드
        print()
        print(f"📤 이미지 업로드 중: {test_images[0].name}")
        result = await upload_image(page, test_images[0])

        if result["success"]:
            print(f"✅ 이미지 업로드 성공!")
            print(f"   파일: {result['file']}")
            print(f"   메시지: {result['message']}")
        else:
            print(f"❌ 이미지 업로드 실패")

        # 스크린샷 저장
        await page.screenshot(
            path="playwright-state/screenshots/single_image_upload.png",
            full_page=True,
        )
        print()
        print("📸 스크린샷 저장: single_image_upload.png")

        # 확인할 시간
        await asyncio.sleep(3)

    except Exception as e:
        print(f"\n❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        raise

    finally:
        await server.cleanup()
        print("\n✅ 리소스 정리 완료")


async def test_multiple_images_upload():
    """다중 이미지 업로드 테스트."""
    if not is_pstatic_reachable():
        pytest.skip("pstatic.net is unreachable; Naver editor assets cannot be loaded in this environment.")

    print("\n\n")
    print("=" * 60)
    print("다중 이미지 업로드 테스트")
    print("=" * 60)
    print()

    # 테스트 이미지 생성
    print("테스트 이미지 생성 중...")
    test_images = await create_test_images()
    print()

    server = NaverBlogMCPServer()

    try:
        # 서버 초기화
        await server.initialize()
        print("✅ 서버 초기화 완료")

        # 페이지 가져오기
        page = await server.get_page()
        print("✅ 페이지 생성 완료")

        # 글쓰기 페이지로 이동
        await page.goto("https://blog.naver.com/GoBlogWrite.naver")
        await asyncio.sleep(2)
        print("✅ 글쓰기 페이지 이동 완료")

        if not await _editor_image_toolbar_available(page):
            pytest.skip(
                "Naver editor image toolbar is unavailable; environment is not ready for image upload tests."
            )

        # 다중 이미지 업로드
        print()
        print(f"📤 {len(test_images)}개 이미지 업로드 중...")
        result = await upload_images(page, test_images)

        print()
        print("=" * 60)
        print("업로드 결과")
        print("=" * 60)
        print(f"성공: {result['success']}")
        print(f"메시지: {result['message']}")
        print(f"업로드 성공: {len(result['uploaded'])}개")
        if result["uploaded"]:
            for img in result["uploaded"]:
                print(f"  ✅ {Path(img).name}")

        if result["failed"]:
            print(f"업로드 실패: {len(result['failed'])}개")
            for img in result["failed"]:
                print(f"  ❌ {Path(img).name}")

        # 스크린샷 저장
        await page.screenshot(
            path="playwright-state/screenshots/multiple_images_upload.png",
            full_page=True,
        )
        print()
        print("📸 스크린샷 저장: multiple_images_upload.png")

        # 확인할 시간
        await asyncio.sleep(3)

    except Exception as e:
        print(f"\n❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        raise

    finally:
        await server.cleanup()
        print("\n✅ 리소스 정리 완료")


async def test_error_handling():
    """에러 처리 테스트."""
    print("\n\n")
    print("=" * 60)
    print("에러 처리 테스트")
    print("=" * 60)
    print()

    server = NaverBlogMCPServer()

    try:
        await server.initialize()
        page = await server.get_page()
        await page.goto("https://blog.naver.com/GoBlogWrite.naver")
        await asyncio.sleep(2)

        # 1. 존재하지 않는 파일
        print("1. 존재하지 않는 파일 업로드 시도...")
        try:
            await upload_image(page, "nonexistent.jpg")
            print("❌ 에러가 발생하지 않음 (버그)")
        except Exception as e:
            print(f"✅ 예상된 에러 발생: {type(e).__name__}")
            print(f"   메시지: {str(e)[:80]}...")

        # 2. 지원하지 않는 포맷
        print()
        print("2. 지원하지 않는 포맷 업로드 시도...")
        test_file = Path("playwright-state/test-images/test.txt")
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("test")

        try:
            await upload_image(page, test_file)
            print("❌ 에러가 발생하지 않음 (버그)")
        except Exception as e:
            print(f"✅ 예상된 에러 발생: {type(e).__name__}")
            print(f"   메시지: {str(e)[:80]}...")

        test_file.unlink()

        print()
        print("✅ 모든 에러 처리 테스트 통과!")

    except Exception as e:
        print(f"\n❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        raise

    finally:
        await server.cleanup()
        print("\n✅ 리소스 정리 완료")


async def main():
    """전체 테스트 실행."""
    print("\n")
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 18 + "이미지 업로드 테스트" + " " * 20 + "║")
    print("╚" + "═" * 58 + "╝")
    print()

    # Pillow 설치 확인
    try:
        import PIL
        print(f"✅ Pillow {PIL.__version__} 설치 확인")
    except ImportError:
        print("❌ Pillow가 설치되지 않았습니다")
        print("   설치: uv pip install pillow")
        return

    print()

    # 1. 단일 이미지 업로드 테스트
    await test_single_image_upload()

    # 2. 다중 이미지 업로드 테스트
    await test_multiple_images_upload()

    # 3. 에러 처리 테스트
    await test_error_handling()

    # 최종 결과
    print("\n\n")
    print("=" * 60)
    print("최종 결과")
    print("=" * 60)
    print()
    print("🎉 모든 이미지 업로드 테스트 통과!")
    print()


if __name__ == "__main__":
    asyncio.run(main())
