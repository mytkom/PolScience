package org.example;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@NoArgsConstructor
@AllArgsConstructor
@Getter
@Setter
@Builder
@JsonInclude(JsonInclude.Include.NON_NULL)
public class HttpBody
{
    private int offset;
    private int size;
    private List<String> objectTypes;
    @Builder.Default
    private Map<String, String> sorting = new HashMap<>();
    @Builder.Default
    private Map<String, Object> filter = new HashMap<>();
}
