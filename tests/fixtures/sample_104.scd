<?xml version="1.0" encoding="UTF-8"?>
<!--
  SCD 导入测试样例（IEC 61850-6 SCL + IEC 61850-80-1 104 映射 Private）。
  结构参照 open-scd 104 插件测试文件（Apache-2.0）与本仓 TypeID 枚举构造，
  覆盖：精确映射（yx/yk/yc/ym/step、SDI 嵌套路径）、CDC 推断（自动 IOA）、
  多 casdu 剔除、IOA 冲突、不支持 ti 跳过。
-->
<SCL xmlns="http://www.iec.ch/61850/2003/SCL"
     xmlns:eTr_104="http://www.iec.ch/61850-80-1/2007/IEC_60870-5-104"
     version="2007" revision="B" release="4">
  <Header id="iec104-tester-sample" version="1" revision="1" toolID="hand-made"/>
  <Substation name="DemoStation" desc="">
    <VoltageLevel name="F1">
      <Bay name="Q1"/>
    </VoltageLevel>
  </Substation>
  <IED name="B1" desc="">
    <AccessPoint name="AP1">
      <Server>
        <LDevice inst="LD0">
          <LN0 lnClass="LLN0" inst="" lnType="LT_LLN0"/>
          <LN prefix="" lnClass="GGIO" inst="1" lnType="LT_GGIO" desc="公共信号">
            <DOI name="Ind1" desc="断路器位置">
              <DAI name="stVal">
                <Private type="IEC_60870_5_104">
                  <eTr_104:Address casdu="1" ioa="1" ti="1"/>
                </Private>
              </DAI>
            </DOI>
            <DOI name="Ind2" desc="隔离开关位置">
              <DAI name="stVal">
                <Private type="IEC_60870_5_104">
                  <eTr_104:Address casdu="1" ioa="2" ti="3"/>
                </Private>
              </DAI>
              <SDI name="Oper">
                <DAI name="ctlVal">
                  <Private type="IEC_60870_5_104">
                    <eTr_104:Address casdu="1" ioa="102" ti="46"/>
                  </Private>
                </DAI>
              </SDI>
            </DOI>
            <DOI name="Bit1" desc="比特串信号">
              <DAI name="stVal">
                <Private type="IEC_60870_5_104">
                  <eTr_104:Address casdu="1" ioa="701" ti="33"/>
                </Private>
              </DAI>
            </DOI>
            <DOI name="Ind3"/>
          </LN>
          <LN prefix="" lnClass="MMXU" inst="1" lnType="LT_MMXU" desc="测量">
            <DOI name="TotW" desc="总有功">
              <DAI name="f">
                <Private type="IEC_60870_5_104">
                  <eTr_104:Address casdu="1" ioa="401" ti="13"/>
                </Private>
              </DAI>
            </DOI>
            <DOI name="TotW2" desc="总有功重复">
              <DAI name="f">
                <Private type="IEC_60870_5_104">
                  <eTr_104:Address casdu="1" ioa="401" ti="13"/>
                </Private>
              </DAI>
            </DOI>
            <DOI name="Phsb" desc="B相">
              <SDI name="cVal">
                <SDI name="mag">
                  <DAI name="f">
                    <Private type="IEC_60870_5_104">
                      <eTr_104:Address casdu="1" ioa="402" ti="36"/>
                    </Private>
                  </DAI>
                </SDI>
              </SDI>
            </DOI>
            <DOI name="MW"/>
          </LN>
          <LN prefix="" lnClass="MMTR" inst="1" lnType="LT_MMTR" desc="电度">
            <DOI name="TotKwh" desc="正向有功电能">
              <DAI name="val">
                <Private type="IEC_60870_5_104">
                  <eTr_104:Address casdu="1" ioa="501" ti="15"/>
                </Private>
              </DAI>
            </DOI>
            <DOI name="Kwh"/>
          </LN>
          <LN prefix="" lnClass="YPSH" inst="1" lnType="LT_YPSH" desc="档位">
            <DOI name="TapChg" desc="分接头位置">
              <DAI name="val">
                <Private type="IEC_60870_5_104">
                  <eTr_104:Address casdu="1" ioa="601" ti="5"/>
                </Private>
              </DAI>
            </DOI>
          </LN>
          <LN prefix="" lnClass="CILO" inst="1" lnType="LT_CILO" desc="联锁">
            <DOI name="Op"/>
          </LN>
        </LDevice>
      </Server>
    </AccessPoint>
  </IED>
  <IED name="B2" desc="">
    <AccessPoint name="AP1">
      <Server>
        <LDevice inst="LD0">
          <LN0 lnClass="LLN0" inst="" lnType="LT_LLN0"/>
          <LN prefix="" lnClass="GGIO" inst="1" lnType="LT_GGIO">
            <DOI name="Ind1" desc="另一个ASDU的信号">
              <DAI name="stVal">
                <Private type="IEC_60870_5_104">
                  <eTr_104:Address casdu="99" ioa="1" ti="1"/>
                </Private>
              </DAI>
            </DOI>
          </LN>
        </LDevice>
      </Server>
    </AccessPoint>
  </IED>
  <DataTypeTemplates>
    <LNodeType id="LT_LLN0" lnClass="LLN0">
      <DO name="Mod" type="DT_SPC"/>
      <DO name="Beh" type="DT_ENS"/>
      <DO name="Health" type="DT_ENS"/>
    </LNodeType>
    <LNodeType id="LT_GGIO" lnClass="GGIO">
      <DO name="Ind1" type="DT_SPC"/>
      <DO name="Ind2" type="DT_DPC"/>
      <DO name="Ind3" type="DT_SPC"/>
      <DO name="Bit1" type="DT_SPC"/>
    </LNodeType>
    <LNodeType id="LT_MMXU" lnClass="MMXU">
      <DO name="TotW" type="DT_MV"/>
      <DO name="TotW2" type="DT_MV"/>
      <DO name="Phsb" type="DT_WYE"/>
      <DO name="MW" type="DT_MV"/>
    </LNodeType>
    <LNodeType id="LT_MMTR" lnClass="MMTR">
      <DO name="TotKwh" type="DT_BCR"/>
      <DO name="Kwh" type="DT_BCR"/>
    </LNodeType>
    <LNodeType id="LT_YPSH" lnClass="YPSH">
      <DO name="TapChg" type="DT_BSC"/>
    </LNodeType>
    <LNodeType id="LT_CILO" lnClass="CILO">
      <DO name="Op" type="DT_ENC"/>
    </LNodeType>
    <DOType id="DT_SPC" cdc="SPC">
      <DA name="stVal" bType="BOOLEAN" fc="ST"/>
      <DA name="ctlVal" bType="BOOLEAN" fc="CO"/>
    </DOType>
    <DOType id="DT_DPC" cdc="DPC">
      <DA name="stVal" bType="Dbpos" fc="ST"/>
      <DA name="ctlVal" bType="BOOLEAN" fc="CO"/>
    </DOType>
    <DOType id="DT_ENS" cdc="ENS">
      <DA name="stVal" bType="INT32" fc="ST"/>
    </DOType>
    <DOType id="DT_MV" cdc="MV">
      <DA name="mag" bType="Struct" type="DT_MagF"/>
      <DA name="f" bType="FLOAT32" fc="MX"/>
    </DOType>
    <DOType id="DT_WYE" cdc="WYE">
      <DA name="cVal" bType="Struct" type="DT_MV"/>
    </DOType>
    <DOType id="DT_BCR" cdc="BCR">
      <DA name="val" bType="INT64" fc="ST"/>
    </DOType>
    <DOType id="DT_BSC" cdc="BSC">
      <DA name="val" bType="INT8" fc="ST"/>
      <DA name="valTrans" bType="BOOLEAN" fc="ST"/>
    </DOType>
    <DOType id="DT_ENC" cdc="ENC">
      <DA name="ctlVal" bType="Enum" fc="CO"/>
    </DOType>
  </DataTypeTemplates>
</SCL>
