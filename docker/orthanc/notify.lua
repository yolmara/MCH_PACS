local notifyUrl = os.getenv("ORTHANC_NOTIFY_URL") or "http://flask-app:5000/dicom/notify"
local notifyToken = os.getenv("ORTHANC_NOTIFY_TOKEN") or ""

local function buildHeaders()
  local headers = { ["Content-Type"] = "application/json" }
  if notifyToken ~= "" then
    headers["X-Orthanc-Token"] = notifyToken
  end
  return headers
end

function OnStoredInstance(instanceId, tags, metadata, origin)
  local payload = string.format('{"instance_id":"%s"}', instanceId)
  local ok, result = pcall(HttpPost, notifyUrl, payload, buildHeaders())
  if not ok then
    print("[Orthanc notify] callback failed for instance " .. tostring(instanceId) .. ": " .. tostring(result))
  end
end
