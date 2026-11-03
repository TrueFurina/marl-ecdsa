"""Strict verification of real exported ledger objects; no synthetic fallback."""
import json
from blockchain.ledger.block import Block, compute_merkle_root

def verify_export(payload):
    if isinstance(payload, dict):
        blocks = payload.get('blocks')
    else:
        blocks = payload
    if not isinstance(blocks, list) or not blocks:
        return {'valid': False, 'error':'需要非空的区块数组（或 {"blocks": [...] }）', 'blocks':[]}
    if len(blocks)>2000:
        return {'valid':False,'error':'最多验证 2000 个区块','blocks':[]}
    result=[]; prev=None; total=0; seen=set()
    for index,raw in enumerate(blocks):
        errors=[]
        if not isinstance(raw,dict):return {'valid':False,'error':f'区块 {index} 格式错误','blocks':result}
        txs=raw.get('transactions',[])
        if not isinstance(txs,list) or len(txs)>10000:return {'valid':False,'error':f'区块 {index} 交易数组无效或超过限制','blocks':result}
        try:
            b=Block.from_dict(raw)
            if not isinstance(raw.get('block_hash'),str) or len(raw['block_hash'])!=64:errors.append('缺少完整已存储 block_hash')
            if b.block_hash!=b._compute_hash():errors.append('区块哈希不匹配')
            if b.block_height!=index:errors.append('区块高度不连续或非零起始')
            if index==0:
                if b.block_hash!=Block.create_genesis().block_hash: errors.append('创世块与当前项目定义不一致')
            elif not b.is_valid_chain_link(prev):errors.append('前序哈希链断裂')
            for tx in b.transactions:
                total+=1
                if tx.tx_id!=tx.compute_hash():errors.append('交易 ID 与内容摘要不匹配')
                if tx.tx_id in seen:errors.append('交易 ID 重复')
                seen.add(tx.tx_id)
            if index>0 and b.state_root!=compute_merkle_root([tx.tx_id for tx in b.transactions]):errors.append('交易 Merkle 根不匹配')
            prev=b
        except Exception as exc:
            errors.append('解析或计算失败：'+str(exc)[:130]); b=None
        result.append({'height':raw.get('block_height',index),'hash':str(raw.get('block_hash',''))[:18], 'transactions':len(txs),'valid':not errors,'reason':'；'.join(dict.fromkeys(errors))})
        if b is None:break
    return {'valid':len(result)==len(blocks) and all(r['valid'] for r in result), 'checked_blocks':len(result),'checked_transactions':total,'blocks':result, 'note':'仅验证本地文件中的一致性；不证明交易已经被网络共识确认，也不包含公钥签名验真。'}
