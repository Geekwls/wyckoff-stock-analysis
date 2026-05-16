import math
import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional
from .market_state import RegimeState, MarketState

class EventDrivenStateEngine:
    """
    威科夫事件驱动状态机操作系统 (Bayesian Regime Filter) - WIE 3.0
    
    实现基于 HMM 的先验预测与后验更新，内置 6x6 非对称转移矩阵，消除绝对判决。
    """
    
    def __init__(self, ema_alpha: float = 0.2):
        self.current_state: str = RegimeState.S0_PANIC_LIQUIDATION.value
        # 初始后验概率 (均匀分布)
        self.state_prob_posterior: Dict[str, float] = {s.value: 1.0/len(RegimeState) for s in RegimeState}
        
        # 威科夫非对称隐马尔可夫转移矩阵 P(S_t | S_{t-1})
        # 行: 当前状态 (S_{t-1}), 列: 下一状态 (S_t)
        self.transition_matrix = {
            RegimeState.S0_PANIC_LIQUIDATION.value: {
                RegimeState.S0_PANIC_LIQUIDATION.value: 0.60, # 恐慌延续
                RegimeState.S1_ABSORPTION.value: 0.35,        # 进入吸收
                RegimeState.S2_NEUTRAL_COMPRESSION.value: 0.05,
                RegimeState.S3_DEMAND_EMERGENCE.value: 0.0,
                RegimeState.S4_MARKUP.value: 0.0,
                RegimeState.S5_DISTRIBUTION.value: 0.0
            },
            RegimeState.S1_ABSORPTION.value: {
                RegimeState.S0_PANIC_LIQUIDATION.value: 0.15, # 吸收失败，再次恐慌(Spring失效)
                RegimeState.S1_ABSORPTION.value: 0.60,        # 持续吸收
                RegimeState.S2_NEUTRAL_COMPRESSION.value: 0.20, # 转入平静收敛
                RegimeState.S3_DEMAND_EMERGENCE.value: 0.05,  # 突发需求
                RegimeState.S4_MARKUP.value: 0.0,
                RegimeState.S5_DISTRIBUTION.value: 0.0
            },
            RegimeState.S2_NEUTRAL_COMPRESSION.value: {
                RegimeState.S0_PANIC_LIQUIDATION.value: 0.10, # 破位下行
                RegimeState.S1_ABSORPTION.value: 0.15,        # 重新被动吸收
                RegimeState.S2_NEUTRAL_COMPRESSION.value: 0.60, # 继续磨底
                RegimeState.S3_DEMAND_EMERGENCE.value: 0.15,  # 需求显现
                RegimeState.S4_MARKUP.value: 0.0,
                RegimeState.S5_DISTRIBUTION.value: 0.0
            },
            RegimeState.S3_DEMAND_EMERGENCE.value: {
                RegimeState.S0_PANIC_LIQUIDATION.value: 0.05, # 极端失败(假突破遭遇黑天鹅)
                RegimeState.S1_ABSORPTION.value: 0.10,        # 需求不足退回吸收
                RegimeState.S2_NEUTRAL_COMPRESSION.value: 0.20, # LPS回踩收敛
                RegimeState.S3_DEMAND_EMERGENCE.value: 0.40,  # 需求继续测试
                RegimeState.S4_MARKUP.value: 0.20,            # 顺利进入主升
                RegimeState.S5_DISTRIBUTION.value: 0.05       # 遇阻直接转派发(极短命)
            },
            RegimeState.S4_MARKUP.value: {
                RegimeState.S0_PANIC_LIQUIDATION.value: 0.0,
                RegimeState.S1_ABSORPTION.value: 0.0,
                RegimeState.S2_NEUTRAL_COMPRESSION.value: 0.15, # 上涨中继(Reaccumulation)
                RegimeState.S3_DEMAND_EMERGENCE.value: 0.15,  # 回踩后重新需求
                RegimeState.S4_MARKUP.value: 0.60,            # 主升延续
                RegimeState.S5_DISTRIBUTION.value: 0.10       # 开始派发(BC)
            },
            RegimeState.S5_DISTRIBUTION.value: {
                RegimeState.S0_PANIC_LIQUIDATION.value: 0.20, # 派发完毕，直接进入溃败
                RegimeState.S1_ABSORPTION.value: 0.0,
                RegimeState.S2_NEUTRAL_COMPRESSION.value: 0.15, # 派发中继
                RegimeState.S3_DEMAND_EMERGENCE.value: 0.05,  # 诱多(Upthrust)
                RegimeState.S4_MARKUP.value: 0.10,            # 重新突破，派发变再吸筹
                RegimeState.S5_DISTRIBUTION.value: 0.50       # 派发延续
            }
        }

    def update(self, row: Dict[str, Any], vsa: Dict[str, Any], aps: Dict[str, Any], 
               regime: Dict[str, Any], rs: Dict[str, Any]) -> MarketState:
        """
        贝叶斯滤波更新 (Bayesian Filter Update)
        1. 预测步 (Prediction): 基于转移矩阵与上一时刻后验概率，推算先验分布。
        2. 更新步 (Update): 根据当前微观特征计算似然度 (Observation Likelihood)，更新后验概率。
        """
        ts = str(row.get('timestamp', 'N/A'))
        close = float(row.get('close', 0.0))
        
        aps_val = float(aps.get('aps', 0.0))
        cds_val = int(regime.get('cds', 0))
        lcs_val = float(regime.get('lcs', 0.0))
        vpoc = float(regime.get('vpoc_price', 0.0))
        exp_eff = float(vsa.get('expansion_efficiency', 0.0))
        clv_val = float(vsa.get('clv', 0.0))
        
        retention = float(rs.get('liquidity_retention', 1.0))
        hs = bool(rs.get('hidden_strength', False))
        hw = bool(rs.get('hidden_weakness', False))
        event_flag = str(regime.get('event_flag', 'NORMAL'))
        
        # --- 1. 预测步 (Prior Prediction) ---
        # P(S_t) = \sum_{S_{t-1}} P(S_t | S_{t-1}) * P_{posterior}(S_{t-1})
        prior_probs = {s.value: 0.0 for s in RegimeState}
        for s_curr in RegimeState:
            for s_prev in RegimeState:
                prior_probs[s_curr.value] += self.transition_matrix[s_prev.value][s_curr.value] * self.state_prob_posterior[s_prev.value]
                
        # 保存这一步推演的未来路径概率（用于向用户展示“路径依赖”）
        transition_paths = {k: v for k, v in prior_probs.items()}
        
        # --- 2. 观察似然函数 P(Obs | S_t) ---
        # 提取微观特征并映射到各状态的似然度，消除硬性截断，采用更加平滑的加权
        likelihood = {s.value: 0.1 for s in RegimeState} # Base likelihood
        
        # 极速溃败出逃保命检查 (溃败特征强)
        is_breakdown = (clv_val < -0.6 and exp_eff < 0.5) or hw
        
        if is_breakdown:
            likelihood[RegimeState.S0_PANIC_LIQUIDATION.value] *= 8.0
            likelihood[RegimeState.S5_DISTRIBUTION.value] *= 2.0
        else:
            # 状态 0: 恐慌/高波动带 (不再是绝对死刑，而是高信息区)
            if aps_val < 5 and cds_val < 10:
                likelihood[RegimeState.S0_PANIC_LIQUIDATION.value] *= 2.0
            
            # 状态 1: 吸收带
            if aps_val > 8:
                likelihood[RegimeState.S1_ABSORPTION.value] *= (1.0 + min(aps_val, 30) / 10.0)
                
            # 状态 2: 换手收敛
            if cds_val > 10:
                likelihood[RegimeState.S2_NEUTRAL_COMPRESSION.value] *= (1.0 + (cds_val / 20.0) + (lcs_val / 10.0))
                
            # 状态 3: 需求萌芽
            if close > vpoc and exp_eff > 1.2:
                likelihood[RegimeState.S3_DEMAND_EMERGENCE.value] *= (2.0 + exp_eff)
            if 'SPRING' in event_flag and aps_val > 10:
                likelihood[RegimeState.S3_DEMAND_EMERGENCE.value] *= 5.0 # Spring事件极大增强需求似然
                
            # 状态 4: 主升浪
            if close > vpoc * 1.05 and exp_eff > 1.5 and retention > 1.1:
                likelihood[RegimeState.S4_MARKUP.value] *= (2.0 + exp_eff + retention)
                
            # 状态 5: 派发
            if clv_val < -0.4 and retention < 0.8:
                likelihood[RegimeState.S5_DISTRIBUTION.value] *= 3.0

        # --- 3. 后验更新 (Posterior Update) ---
        # P(S_t | Obs) = P(Obs | S_t) * P(S_t) / P(Obs)
        unnormalized_posterior = {s.value: likelihood[s.value] * prior_probs[s.value] for s in RegimeState}
        total_p = sum(unnormalized_posterior.values())
        
        # 为了防止某种状态完全锁死为0（虽然转移矩阵和似然度都加了基数防0），加上小 $\epsilon$ 平滑
        epsilon = 1e-4
        for k in unnormalized_posterior:
            unnormalized_posterior[k] += epsilon
        total_p = sum(unnormalized_posterior.values())
        
        self.state_prob_posterior = {k: v / total_p for k, v in unnormalized_posterior.items()}

        # 4. 计算状态熵 H(S)
        entropy = 0.0
        for p in self.state_prob_posterior.values():
            if p > 0:
                entropy -= p * math.log(p)

        # 5. 判定是否触发置信度降级自保令
        # 6个离散状态的最大可能熵为 ln(6) approx 1.7917
        is_degraded = (entropy > 1.55)

        # 确定主导状态 (最高概率标签，用于UI展示，但决策层将使用完整概率分布)
        dominant_state = max(self.state_prob_posterior.items(), key=lambda x: x[1])[0]
        if is_degraded:
            self.current_state = f"[?] 高熵模糊带 ({dominant_state.split('(')[0].strip()})"
        else:
            self.current_state = dominant_state

        flags = []
        if event_flag != 'NORMAL':
            flags.append(event_flag)
        if hs:
            flags.append('FLAG: HIDDEN STRENGTH')
        if hw:
            flags.append('FLAG: HIDDEN WEAKNESS')

        return MarketState(
            timestamp=ts,
            close=close,
            regime=self.current_state,
            aps=aps_val,
            cds=cds_val,
            lcs=lcs_val,
            vpoc_price=vpoc,
            expansion_eff=exp_eff,
            clv=clv_val,
            liquidity_retention=retention,
            hidden_strength=hs,
            hidden_weakness=hw,
            event_flags=flags,
            state_probs=self.state_prob_posterior.copy(),
            transition_paths=transition_paths,
            state_entropy=entropy,
            is_confidence_degraded=is_degraded
        )
