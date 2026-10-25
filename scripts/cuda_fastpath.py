"""Optional runtime-only CUDA MoE decode batching; original model files stay untouched."""
from types import MethodType


def enable_turbo(model):
    import torch
    import torch.nn.functional as functional
    changed = 0
    for module in model.modules():
        if type(module).__name__ != 'DeepseekV2MoE' or module.ep_size != 1:
            continue
        original = module.moe_infer

        def infer(owner, x, ids, weights, fallback=original):
            if x.shape[0] != 1:
                return fallback(x, ids, weights)
            # One host sync instead of counts + per-expert dynamic dispatch each layer.
            chosen = ids[0].tolist()
            gate = torch.stack([owner.experts[i].gate_proj.weight for i in chosen])
            up = torch.stack([owner.experts[i].up_proj.weight for i in chosen])
            down = torch.stack([owner.experts[i].down_proj.weight for i in chosen])
            inputs = x.expand(len(chosen), -1).unsqueeze(-1)
            hidden = functional.silu(torch.bmm(gate, inputs)) * torch.bmm(up, inputs)
            outputs = torch.bmm(down, hidden).squeeze(-1)
            return (outputs.to(weights.dtype) * weights[0, :, None]).sum(0, keepdim=True).to(x.dtype)

        module.moe_infer = MethodType(infer, module)
        changed += 1
    if not changed:
        raise RuntimeError('Turbo is unsupported by this model architecture; no model changes applied.')
    return changed
