use serde_json::{Value, json};
use std::{collections::HashMap, mem::size_of};
use windows::{
    Win32::{
        Graphics::Dxgi::{CreateDXGIFactory1, IDXGIFactory1},
        System::{
            Performance::*,
            ProcessStatus::{GetPerformanceInfo, PERFORMANCE_INFORMATION},
        },
    },
    core::PCWSTR,
};

pub struct Device {
    pub name: String,
    key: String,
    dedicated: usize,
}

pub fn device() -> Result<Device, String> {
    // COM wrappers release the factory and adapters on every exit path.
    let factory: IDXGIFactory1 = unsafe { CreateDXGIFactory1() }.map_err(|e| e.to_string())?;
    let mut selected = None;
    for index in 0..32 {
        let Ok(adapter) = (unsafe { factory.EnumAdapters1(index) }) else {
            break;
        };
        let desc = unsafe { adapter.GetDesc1() }.map_err(|e| e.to_string())?;
        if desc.VendorId == 0x10de && desc.DedicatedVideoMemory > 0 {
            let end = desc.Description.iter().position(|c| *c == 0).unwrap_or(128);
            if selected.is_some() {
                return Err("Multiple NVIDIA adapters: hardware mapping unavailable".into());
            }
            selected = Some(Device {
                name: String::from_utf16_lossy(&desc.Description[..end]),
                key: format!(
                    "luid_0x{:08x}_0x{:08x}_phys_0",
                    desc.AdapterLuid.HighPart as u32, desc.AdapterLuid.LowPart
                ),
                dedicated: desc.DedicatedVideoMemory,
            });
        }
    }
    selected.ok_or_else(|| "No NVIDIA DXGI adapter available".into())
}

pub struct Query {
    handle: PDH_HQUERY,
    cpu: Option<PDH_HCOUNTER>,
    frequency: Option<PDH_HCOUNTER>,
    engines: Option<PDH_HCOUNTER>,
    memory: Option<PDH_HCOUNTER>,
}

fn checked(status: u32) -> Result<(), String> {
    if status == 0 {
        Ok(())
    } else {
        Err(format!("Windows performance counter error 0x{status:08x}"))
    }
}

impl Query {
    pub fn new() -> Result<Self, String> {
        let mut handle = PDH_HQUERY::default();
        checked(unsafe { PdhOpenQueryW(PCWSTR::null(), 0, &mut handle) })?;
        let mut query = Self {
            handle,
            cpu: None,
            frequency: None,
            engines: None,
            memory: None,
        };
        query.cpu = query.add(r"\Processor Information(_Total)\% Processor Time");
        query.frequency = query.add(r"\Processor Information(_Total)\Processor Frequency");
        query.engines = query.add(r"\GPU Engine(*)\Utilization Percentage");
        query.memory = query.add(r"\GPU Adapter Memory(*)\Dedicated Usage");
        query.collect()?;
        Ok(query)
    }

    fn add(&self, path: &str) -> Option<PDH_HCOUNTER> {
        let wide: Vec<u16> = path.encode_utf16().chain(Some(0)).collect();
        let mut counter = PDH_HCOUNTER::default();
        (unsafe { PdhAddEnglishCounterW(self.handle, PCWSTR(wide.as_ptr()), 0, &mut counter) } == 0)
            .then_some(counter)
    }

    pub fn collect(&self) -> Result<(), String> {
        checked(unsafe { PdhCollectQueryData(self.handle) })
    }

    fn number(&self, counter: Option<PDH_HCOUNTER>) -> Option<f64> {
        let mut value = PDH_FMT_COUNTERVALUE::default();
        if unsafe { PdhGetFormattedCounterValue(counter?, PDH_FMT_DOUBLE, None, &mut value) } != 0
            || value.CStatus > 1
        {
            return None;
        }
        finite(unsafe { value.Anonymous.doubleValue })
    }

    fn array(&self, counter: Option<PDH_HCOUNTER>) -> Option<Vec<(String, f64)>> {
        let counter = counter?;
        // Instances can change between the size probe and read; retry with a fresh probe.
        for _ in 0..3 {
            let (mut bytes, mut count) = (0, 0);
            let status = unsafe {
                PdhGetFormattedCounterArrayW(counter, PDH_FMT_DOUBLE, &mut bytes, &mut count, None)
            };
            if status != PDH_MORE_DATA || bytes == 0 || bytes > 16 * 1024 * 1024 {
                return None;
            }
            // u64 storage preserves the native structure's 8-byte alignment.
            let mut buffer = vec![0u64; (bytes as usize).div_ceil(8)];
            let ptr = buffer.as_mut_ptr().cast::<PDH_FMT_COUNTERVALUE_ITEM_W>();
            let status = unsafe {
                PdhGetFormattedCounterArrayW(
                    counter,
                    PDH_FMT_DOUBLE,
                    &mut bytes,
                    &mut count,
                    Some(ptr),
                )
            };
            if status == PDH_MORE_DATA {
                continue;
            }
            if status != 0
                || count as usize * size_of::<PDH_FMT_COUNTERVALUE_ITEM_W>() > buffer.len() * 8
            {
                return None;
            }
            let mut result = Vec::new();
            for item in unsafe { std::slice::from_raw_parts(ptr, count as usize) } {
                if item.FmtValue.CStatus <= 1
                    && !item.szName.is_null()
                    && let Some(value) = finite(unsafe { item.FmtValue.Anonymous.doubleValue })
                {
                    result.push((unsafe { item.szName.to_string() }.ok()?, value));
                }
            }
            return Some(result);
        }
        None
    }

    pub fn read(&self, device: Option<&Device>) -> Value {
        let mut value = json!({
            "cpu": self.number(self.cpu).map(|v| v.min(100.0)),
            "cpu_mhz": self.number(self.frequency),
            "cpu_source": "Windows busy time", "gpu_source": "Windows busiest engine",
            "gpu": null, "vram_used": null, "vram_total": null,
        });
        if let Some(device) = device {
            value["gpu_name"] = json!(device.name);
            value["gpu_adapter"] = json!(device.key);
            value["gpu"] = json!(
                self.array(self.engines)
                    .and_then(|items| busiest_engine(&items, &device.key))
            );
            value["vram_total"] = json!(device.dedicated as f64 / 1048576.0);
            value["vram_used"] = json!(
                self.array(self.memory)
                    .and_then(|items| items
                        .into_iter()
                        .find(|(name, _)| name.eq_ignore_ascii_case(&device.key)))
                    .map(|(_, bytes)| bytes / 1048576.0)
            );
        }
        value
    }
}
impl Drop for Query {
    fn drop(&mut self) {
        unsafe {
            PdhCloseQuery(self.handle);
        }
    }
}

pub fn memory(value: &mut Value) -> Result<(), String> {
    let mut info = PERFORMANCE_INFORMATION {
        cb: size_of::<PERFORMANCE_INFORMATION>() as u32,
        ..Default::default()
    };
    unsafe { GetPerformanceInfo(&mut info, size_of::<PERFORMANCE_INFORMATION>() as u32) }
        .map_err(|e| e.to_string())?;
    let gib = info.PageSize as f64 / 1073741824.0;
    value["ram_used"] =
        json!(info.PhysicalTotal.saturating_sub(info.PhysicalAvailable) as f64 * gib);
    value["ram_total"] = json!(info.PhysicalTotal as f64 * gib);
    value["commit_used"] = json!(info.CommitTotal as f64 * gib);
    value["commit_total"] = json!(info.CommitLimit as f64 * gib);
    Ok(())
}

pub fn finite(value: f64) -> Option<f64> {
    (value.is_finite() && value >= 0.0).then_some(value)
}

fn busiest_engine(items: &[(String, f64)], adapter: &str) -> Option<f64> {
    let mut engines = HashMap::<String, f64>::new();
    for (name, value) in items {
        let Some((_, key)) = name.split_once("_luid_") else {
            continue;
        };
        let key = format!("luid_{key}").to_lowercase();
        if key.starts_with(&format!("{adapter}_eng_")) && finite(*value).is_some() {
            *engines.entry(key).or_default() += value;
        }
    }
    engines
        .values()
        .copied()
        .reduce(f64::max)
        .map(|v| v.min(100.0))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn aggregate_same_engine_only_on_selected_adapter() {
        let adapter = "luid_0x00000000_0x00000001_phys_0";
        let items = vec![
            (format!("pid_10_{adapter}_eng_0_engtype_3D"), 20.0),
            (format!("pid_11_{adapter}_eng_0_engtype_3D"), 30.0),
            (format!("pid_10_{adapter}_eng_1_engtype_Copy"), 40.0),
            (
                "pid_10_luid_0x00000000_0x00000002_phys_0_eng_0_engtype_3D".into(),
                100.0,
            ),
        ];
        assert_eq!(busiest_engine(&items, adapter), Some(50.0));
        assert_eq!(
            busiest_engine(
                &[(format!("pid_10_{adapter}_eng_0_engtype_3D"), 0.0)],
                adapter
            ),
            Some(0.0)
        );
        assert_eq!(busiest_engine(&[], adapter), None);
        for value in [f64::NAN, f64::INFINITY, -1.0] {
            assert_eq!(finite(value), None);
        }
    }
}
