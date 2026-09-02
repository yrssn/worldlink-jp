<script setup lang="ts">
import type { InfluencerProfileFields } from '@/api/influencer'

/** 存量 Excel 表头对应的「人 / 建联」维度字段表单片段（新建 / 详情编辑共用），需放在 el-form 内。 */
const model = defineModel<InfluencerProfileFields>({ required: true })
</script>

<template>
  <el-row :gutter="12">
    <el-col :span="12">
      <el-form-item label="KOL 编号">
        <el-input v-model="model.code" placeholder="如 LXDRB001" />
      </el-form-item>
    </el-col>
    <el-col :span="12">
      <el-form-item label="KOL 公司名">
        <el-input v-model="model.company" />
      </el-form-item>
    </el-col>
    <el-col :span="12">
      <el-form-item label="性别">
        <el-select v-model="model.gender" clearable placeholder="未填" style="width: 100%">
          <el-option label="女" value="女" />
          <el-option label="男" value="男" />
        </el-select>
      </el-form-item>
    </el-col>
    <el-col :span="12">
      <el-form-item label="来源渠道">
        <el-input v-model="model.source_channel" placeholder="如「马总推荐」" />
      </el-form-item>
    </el-col>
    <el-col :span="12">
      <el-form-item label="建联负责人">
        <el-input v-model="model.contact_owner" />
      </el-form-item>
    </el-col>
    <el-col :span="12">
      <el-form-item label="落地负责人">
        <el-input v-model="model.landing_owner" />
      </el-form-item>
    </el-col>
    <el-col :span="12">
      <el-form-item label="建联开始日期">
        <el-date-picker
          v-model="model.contact_started_at"
          type="date"
          value-format="YYYY-MM-DDT00:00:00"
          placeholder="选择日期"
          style="width: 100%"
        />
      </el-form-item>
    </el-col>
    <el-col :span="12">
      <el-form-item label="计划首次来访">
        <el-date-picker
          v-model="model.planned_visit_at"
          type="date"
          value-format="YYYY-MM-DDT00:00:00"
          placeholder="选择日期"
          style="width: 100%"
        />
      </el-form-item>
    </el-col>
    <el-col :span="8">
      <el-form-item label="是否推特">
        <el-select v-model="model.has_twitter" clearable placeholder="未填" style="width: 100%">
          <el-option label="是" :value="true" />
          <el-option label="否" :value="false" />
        </el-select>
      </el-form-item>
    </el-col>
    <el-col :span="8">
      <el-form-item label="推特渠道">
        <el-input v-model="model.twitter_channel" placeholder="如 Line" />
      </el-form-item>
    </el-col>
    <el-col :span="8">
      <el-form-item label="群名称">
        <el-input v-model="model.group_name" />
      </el-form-item>
    </el-col>
  </el-row>
</template>
