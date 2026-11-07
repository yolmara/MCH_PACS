local notifyUrl = os.getenv("ORTHANC_NOTIFY_URL") or "http://flask-app:5000/dicom/notify"
local notifyToken = os.getenv("ORTHANC_NOTIFY_TOKEN") or ""

local function buildHeaders()
  local headers = { ["Content-Type"] = "application/json" }
  if notifyToken ~= "" then
    headers["X-Orthanc-Token"] = notifyToken
  end
  return headers
end

-- Called once per study, after the study has stopped receiving new instances for
-- "StableAge" seconds (60 by default). The old OnStoredInstance hook ran once per
-- slice, inside the request that stored it, so a slow Flask reply held up every
-- upload and scanner push. This one runs later, in Orthanc's background event
-- thread, and Flask answers it immediately and does the real work in the background.
function OnStableStudy(studyId, tags, metadata)
  local payload = string.format('{"study_id":"%s"}', studyId)
  local ok, result = pcall(HttpPost, notifyUrl, payload, buildHeaders())
  if not ok then
    print("[Orthanc notify] callback failed for study " .. tostring(studyId) .. ": " .. tostring(result))
  end
end
