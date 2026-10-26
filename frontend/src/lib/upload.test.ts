import { describe, expect, it } from "vitest";

import { CONFIG, pdfFile } from "../test/fixtures.ts";
import { acceptAttribute, checkFile, describeAccepted } from "./upload.ts";

describe("checkFile", () => {
  it("accepts PDF, JPEG and PNG within the limit", () => {
    expect(checkFile(pdfFile(), CONFIG)).toBeNull();
    expect(checkFile(new File(["x"], "r.JPG", { type: "image/jpeg" }), CONFIG)).toBeNull();
    expect(checkFile(new File(["x"], "r.png", { type: "image/png" }), CONFIG)).toBeNull();
  });

  it("refuses other types by extension or by MIME", () => {
    expect(checkFile(new File(["x"], "notes.txt", { type: "text/plain" }), CONFIG)?.code).toBe("type");
    expect(checkFile(new File(["x"], "fake.pdf", { type: "text/plain" }), CONFIG)?.code).toBe("type");
    expect(checkFile(new File(["x"], "image.gif", { type: "image/gif" }), CONFIG)?.code).toBe("type");
  });

  it("lets the extension decide when the browser reports no MIME type", () => {
    expect(checkFile(new File(["x"], "scan.pdf", { type: "" }), CONFIG)).toBeNull();
  });

  it("refuses empty and oversized files", () => {
    expect(checkFile(pdfFile("empty.pdf", 0), CONFIG)?.code).toBe("empty");
    const big = checkFile(pdfFile("big.pdf", 2 * 1024 * 1024), { ...CONFIG, max_upload_mb: 1 });
    expect(big).toEqual({ code: "size", message: "Larger than the 1 MB limit." });
  });

  it("describes the accepted types", () => {
    expect(describeAccepted(CONFIG)).toBe("PDF, JPG or PNG");
    expect(acceptAttribute(CONFIG)).toBe(".pdf,application/pdf,.jpg,.jpeg,image/jpeg,.png,image/png");
  });
});
