package org.example;

import java.util.List;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
@JsonIgnoreProperties(ignoreUnknown = true)
public class InstitutionObject
{

    private String country;
    private String federationNumber;
    private List<Address> addresses;
    private String regon;
    private List<Object> targetInstitutions;
    private String countryCd;
    private String pib;
    private String institutionUuid;
    private String lNumber;
    private String managerName;
    private List<SupervisingInstitution> supervisingInstitutions;
    private String eMail;
    private String supervisingInstitutionID;
    private String nip;
    private String www;
    private String managerSurnamePrefix;
    private String managerFunction;
    private String espAddress;
    private String id;
    private String iKindName;
    private String edaAddress;
    private String postalCd;
    private String managerOtherNames;
    private String bNumber;
    private String panNumber;
    private List<Object> branches;
    private String supervisingInstitutionName;
    private String iLiqStartDT;
    private String eunNumber;
    private String uTypeName;
    private String phone;
    private String iStartDT;
    private String iLiqDT;
    private String name;
    private List<Status> statuses;
    private String iKindCd;
    private String yearPib;
    private String dataSource;
    private String status;
    private String statusCode;
    private String city;
    private String managerSurname;
    private String siTypeName;
    private String managerEmployeeInInstitutionUuid;
    private String ministryNumber;
    private String street;
    private String voivodeship;
    private List<Object> transformedInstitutions;
    private List<Type> types;
    private String lastRefresh;
    private String krs;
    private List<NameRecord> names;
    private String institutionUid;
    private String siTypeCd;
    private String uTypeCd;
    private String voivodeshipCode;
}
