"""WSDL 1.1 (document/literal, SOAP 1.1) мок-сервиса СПАРК."""

NS = "urn:mock:spark:v1"

WSDL_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<wsdl:definitions name="MockSpark"
    targetNamespace="urn:mock:spark:v1"
    xmlns:tns="urn:mock:spark:v1"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"
    xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/">
  <wsdl:documentation>Учебный мок по мотивам СПАРК-Интерфакс. Не настоящий API Интерфакса и не его копия.
Все компании вымышленные. Сначала Authenticate, затем SessionId в SOAP Header каждого запроса.</wsdl:documentation>
  <wsdl:types>
    <xsd:schema targetNamespace="urn:mock:spark:v1" elementFormDefault="qualified">
      <xsd:simpleType name="Inn">
        <xsd:restriction base="xsd:string"><xsd:pattern value="[0-9]{10}"/></xsd:restriction>
      </xsd:simpleType>
      <xsd:simpleType name="CompanyStatus">
        <xsd:restriction base="xsd:string">
          <xsd:enumeration value="ACTIVE"/><xsd:enumeration value="LIQUIDATING"/><xsd:enumeration value="LIQUIDATED"/>
        </xsd:restriction>
      </xsd:simpleType>
      <xsd:simpleType name="GroupRole">
        <xsd:restriction base="xsd:string">
          <xsd:enumeration value="parent"/><xsd:enumeration value="subsidiary"/><xsd:enumeration value="affiliate"/>
        </xsd:restriction>
      </xsd:simpleType>
      <xsd:complexType name="Okved">
        <xsd:sequence>
          <xsd:element name="Code" type="xsd:string"/>
          <xsd:element name="Name" type="xsd:string"/>
        </xsd:sequence>
      </xsd:complexType>
      <xsd:complexType name="Head">
        <xsd:sequence>
          <xsd:element name="FullName" type="xsd:string"/>
          <xsd:element name="Position" type="xsd:string"/>
        </xsd:sequence>
      </xsd:complexType>
      <xsd:complexType name="Company">
        <xsd:sequence>
          <xsd:element name="INN" type="tns:Inn"/>
          <xsd:element name="OGRN" type="xsd:string"/>
          <xsd:element name="KPP" type="xsd:string"/>
          <xsd:element name="ShortName" type="xsd:string"/>
          <xsd:element name="FullName" type="xsd:string"/>
          <xsd:element name="Status" type="tns:CompanyStatus"/>
          <xsd:element name="RegistrationDate" type="xsd:date"/>
          <xsd:element name="RegionCode" type="xsd:string"/>
          <xsd:element name="LegalAddress" type="xsd:string"/>
          <xsd:element name="OKVED" type="tns:Okved"/>
          <xsd:element name="AuthorizedCapital" type="xsd:long"/>
          <xsd:element name="EmployeeCount" type="xsd:int"/>
          <xsd:element name="Head" type="tns:Head"/>
          <xsd:element name="GroupId" type="xsd:string" nillable="true"/>
          <xsd:element name="Revision" type="xsd:int"/>
          <xsd:element name="ActualDate" type="xsd:dateTime"/>
        </xsd:sequence>
      </xsd:complexType>
      <xsd:complexType name="CompanyListItem">
        <xsd:sequence>
          <xsd:element name="INN" type="tns:Inn"/>
          <xsd:element name="ShortName" type="xsd:string"/>
          <xsd:element name="Status" type="tns:CompanyStatus"/>
        </xsd:sequence>
      </xsd:complexType>
      <xsd:complexType name="GroupMember">
        <xsd:sequence>
          <xsd:element name="INN" type="tns:Inn"/>
          <xsd:element name="ShortName" type="xsd:string"/>
          <xsd:element name="Role" type="tns:GroupRole"/>
          <xsd:element name="SharePercent" type="xsd:decimal"/>
          <xsd:element name="Status" type="tns:CompanyStatus"/>
        </xsd:sequence>
      </xsd:complexType>
      <xsd:complexType name="ChangedCompany">
        <xsd:sequence>
          <xsd:element name="INN" type="tns:Inn"/>
          <xsd:element name="ChangedAt" type="xsd:dateTime"/>
          <xsd:element name="ChangeType" type="xsd:string"/>
        </xsd:sequence>
      </xsd:complexType>

      <xsd:element name="SessionId" type="xsd:string"/>

      <xsd:element name="Authenticate">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="Login" type="xsd:string"/>
          <xsd:element name="Password" type="xsd:string"/>
        </xsd:sequence></xsd:complexType>
      </xsd:element>
      <xsd:element name="AuthenticateResponse">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="SessionId" type="xsd:string"/>
          <xsd:element name="ExpiresAt" type="xsd:dateTime"/>
        </xsd:sequence></xsd:complexType>
      </xsd:element>

      <xsd:element name="GetCompanyList">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="Page" type="xsd:int" minOccurs="0"/>
          <xsd:element name="PageSize" type="xsd:int" minOccurs="0"/>
        </xsd:sequence></xsd:complexType>
      </xsd:element>
      <xsd:element name="GetCompanyListResponse">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="Total" type="xsd:int"/>
          <xsd:element name="Page" type="xsd:int"/>
          <xsd:element name="Companies"><xsd:complexType><xsd:sequence>
            <xsd:element name="Company" type="tns:CompanyListItem" minOccurs="0" maxOccurs="unbounded"/>
          </xsd:sequence></xsd:complexType></xsd:element>
        </xsd:sequence></xsd:complexType>
      </xsd:element>

      <xsd:element name="GetCompanyShortReport">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="INN" type="xsd:string"/>
        </xsd:sequence></xsd:complexType>
      </xsd:element>
      <xsd:element name="GetCompanyShortReportResponse">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="Company" type="tns:Company"/>
        </xsd:sequence></xsd:complexType>
      </xsd:element>

      <xsd:element name="GetCompanyGroup">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="INN" type="xsd:string"/>
        </xsd:sequence></xsd:complexType>
      </xsd:element>
      <xsd:element name="GetCompanyGroupResponse">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="GroupId" type="xsd:string" nillable="true"/>
          <xsd:element name="GroupName" type="xsd:string" nillable="true"/>
          <xsd:element name="Members"><xsd:complexType><xsd:sequence>
            <xsd:element name="Member" type="tns:GroupMember" minOccurs="0" maxOccurs="unbounded"/>
          </xsd:sequence></xsd:complexType></xsd:element>
        </xsd:sequence></xsd:complexType>
      </xsd:element>

      <xsd:element name="GetChangedCompanies">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="Since" type="xsd:dateTime"/>
          <xsd:element name="Page" type="xsd:int" minOccurs="0"/>
          <xsd:element name="PageSize" type="xsd:int" minOccurs="0"/>
        </xsd:sequence></xsd:complexType>
      </xsd:element>
      <xsd:element name="GetChangedCompaniesResponse">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="Total" type="xsd:int"/>
          <xsd:element name="Page" type="xsd:int"/>
          <xsd:element name="Changes"><xsd:complexType><xsd:sequence>
            <xsd:element name="Change" type="tns:ChangedCompany" minOccurs="0" maxOccurs="unbounded"/>
          </xsd:sequence></xsd:complexType></xsd:element>
        </xsd:sequence></xsd:complexType>
      </xsd:element>

      <xsd:element name="SparkFault">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="ErrorCode" type="xsd:string"/>
          <xsd:element name="Message" type="xsd:string"/>
        </xsd:sequence></xsd:complexType>
      </xsd:element>
    </xsd:schema>
  </wsdl:types>

  <wsdl:message name="SessionHeader"><wsdl:part name="SessionId" element="tns:SessionId"/></wsdl:message>
  <wsdl:message name="Fault"><wsdl:part name="fault" element="tns:SparkFault"/></wsdl:message>
{messages}
  <wsdl:portType name="SparkPortType">
{port_ops}
  </wsdl:portType>

  <wsdl:binding name="SparkBinding" type="tns:SparkPortType">
    <soap:binding style="document" transport="http://schemas.xmlsoap.org/soap/http"/>
{binding_ops}
  </wsdl:binding>

  <wsdl:service name="SparkService">
    <wsdl:port name="SparkPort" binding="tns:SparkBinding">
      <soap:address location="{address}"/>
    </wsdl:port>
  </wsdl:service>
</wsdl:definitions>
"""

OPERATIONS = ["Authenticate", "GetCompanyList", "GetCompanyShortReport", "GetCompanyGroup", "GetChangedCompanies"]


def render_wsdl(address: str) -> str:
    messages, port_ops, binding_ops = [], [], []
    for op in OPERATIONS:
        messages.append(f'  <wsdl:message name="{op}Request"><wsdl:part name="parameters" element="tns:{op}"/></wsdl:message>')
        messages.append(f'  <wsdl:message name="{op}Response"><wsdl:part name="parameters" element="tns:{op}Response"/></wsdl:message>')
        port_ops.append(
            f'    <wsdl:operation name="{op}">\n'
            f'      <wsdl:input message="tns:{op}Request"/>\n'
            f'      <wsdl:output message="tns:{op}Response"/>\n'
            f'      <wsdl:fault name="SparkFault" message="tns:Fault"/>\n'
            f'    </wsdl:operation>')
        header = "" if op == "Authenticate" else \
            '        <soap:header message="tns:SessionHeader" part="SessionId" use="literal"/>\n'
        binding_ops.append(
            f'    <wsdl:operation name="{op}">\n'
            f'      <soap:operation soapAction="urn:mock:spark:v1/{op}"/>\n'
            f'      <wsdl:input>\n{header}        <soap:body use="literal"/>\n      </wsdl:input>\n'
            f'      <wsdl:output><soap:body use="literal"/></wsdl:output>\n'
            f'      <wsdl:fault name="SparkFault"><soap:fault name="SparkFault" use="literal"/></wsdl:fault>\n'
            f'    </wsdl:operation>')
    from xml.sax.saxutils import quoteattr
    return (WSDL_TEMPLATE.replace("{messages}", "\n".join(messages))
            .replace("{port_ops}", "\n".join(port_ops))
            .replace("{binding_ops}", "\n".join(binding_ops))
            .replace('"{address}"', quoteattr(address)))
