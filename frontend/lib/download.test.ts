import { describe, expect, it } from "vitest";

import { projectExportQueryString } from "@/lib/api/endpoints";
import { filenameFromDisposition } from "@/lib/download";

describe("projectExportQueryString", () => {
  it("repeats include and moduleIds the way FastAPI reads a list", () => {
    expect(
      projectExportQueryString({
        include: ["checklist", "mockData"],
        moduleIds: ["m1", "m2"],
        status: "fail",
      }),
    ).toBe("?include=checklist&include=mockData&moduleIds=m1&moduleIds=m2&status=fail");
  });

  it("sends no moduleIds for every module", () => {
    expect(projectExportQueryString({ include: ["mockData"], moduleIds: [] })).toBe(
      "?include=mockData",
    );
  });
});

describe("filenameFromDisposition", () => {
  it("reads the quoted filename", () => {
    expect(filenameFromDisposition('attachment; filename="qa-export.zip"')).toBe(
      "qa-export.zip",
    );
  });

  it("falls back when the header is missing or has no filename", () => {
    expect(filenameFromDisposition(null)).toBe("export");
    expect(filenameFromDisposition("attachment")).toBe("export");
  });
});
